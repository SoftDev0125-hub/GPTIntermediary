#!/usr/bin/env python3
"""
Build a portable Windows bundle for GPTIntermediary.

Output:
    dist/GPTIntermediary/

This bundle can run on target PCs without system-installed Python/Node/PostgreSQL.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "GPTIntermediary"
PYI_WORK = ROOT / "build" / "pyi-work"
PYI_SPEC = ROOT / "build" / "pyi-spec"

# MSVC UCRT DLLs expected by CPython / PyInstaller / Node on clean Windows PCs
_MSVC_RUNTIME_DLLS = (
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll",
    "concrt140.dll",
)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"[RUN] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd or ROOT), check=True)


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except Exception:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def ensure_python_packages_for_build() -> None:
    """Fail fast if the interpreter running this script cannot import core deps (common venv mix-up)."""
    required = (
        "fastapi",
        "uvicorn",
        "starlette",
        "pydantic",
        "flask",
        "django",
        "dotenv",
    )
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "This Python cannot import: "
            + ", ".join(missing)
            + ". Activate your project venv (or install requirements) and run build again:\n"
            + "  pip install -r requirements.txt"
        )


def _npm_executable() -> str:
    """Resolve npm for subprocess (Windows often needs npm.cmd, not bare 'npm')."""
    if sys.platform == "win32":
        for name in ("npm.cmd", "npm"):
            found = shutil.which(name)
            if found:
                return found
    else:
        found = shutil.which("npm")
        if found:
            return found
    raise RuntimeError(
        "npm not found in PATH. Install Node.js from https://nodejs.org/ "
        "and reopen the terminal so npm is available, then run build.py again."
    )


def ensure_node_modules() -> None:
    package_json = ROOT / "package.json"
    if not package_json.exists():
        raise RuntimeError("package.json not found in project root.")
    npm = _npm_executable()
    print("[*] Installing Node production dependencies (no devDependencies)...")
    lock = ROOT / "package-lock.json"
    if lock.is_file():
        r = subprocess.run(
            [npm, "ci", "--omit=dev"],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            print("[!] npm ci failed; falling back to npm install --omit=dev")
            run([npm, "install", "--omit=dev"], cwd=ROOT)
    else:
        run([npm, "install", "--omit=dev"], cwd=ROOT)
    run([npm, "prune", "--omit=dev"], cwd=ROOT)


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _collect_all_args(packages: tuple[str, ...]) -> list[str]:
    """PyInstaller often misses lazy/dynamic imports; --collect-all pulls full distributions."""
    out: list[str] = []
    for pkg in packages:
        out.extend(["--collect-all", pkg])
    return out


def pyinstaller_build(script: Path, name: str, extra_args: list[str] | None = None) -> None:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        name,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(PYI_WORK),
        "--specpath",
        str(PYI_SPEC),
    ]
    if extra_args:
        args.extend(extra_args)
    args.append(str(script))
    run(args, cwd=ROOT)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _include_puppeteer_browser_downloads() -> bool:
    """Bundled Chromium is huge (~0.3-1+ GB). Default OFF; set PORTABLE_INCLUDE_PUPPETEER_CHROME=1 to ship it."""
    return os.getenv("PORTABLE_INCLUDE_PUPPETEER_CHROME", "").strip().lower() in ("1", "true", "yes")


def ignore_node_modules_portable(cur_dir: str, names: list[str]) -> set[str]:
    """
    Skip bloat under node_modules when copying into the portable bundle.
    Safe skips: docs/tests/maps, local dev caches, optional Puppeteer browser download.
    """
    ignored: set[str] = set()
    d = os.path.normpath(cur_dir).replace("\\", "/").lower()
    include_chrome = _include_puppeteer_browser_downloads()
    for name in names:
        nl = name.lower()
        if nl.endswith(".map"):
            ignored.add(name)
        if nl.endswith(".md") or nl.endswith(".markdown"):
            ignored.add(name)
        if nl == ".wwebjs_cache":
            ignored.add(name)
        if not include_chrome and (
            nl == ".local-chromium"
            or nl.startswith("chrome-headless-shell")
            or (nl.startswith("chrome-") and ("puppeteer" in d or "puppeteer-core" in d))
        ):
            ignored.add(name)
        if nl in ("__tests__", "test", "tests", "docs", "examples", ".github") and d.count("node_modules") >= 2:
            ignored.add(name)
    return ignored


def copy_app_node_modules(src: Path, dst: Path) -> None:
    """Copy node_modules into the portable app tree with pruning (much smaller than raw copy)."""
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore_node_modules_portable)
    print("[*] node_modules copied with portable pruning (see PORTABLE_README.txt).")


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def bundle_msvc_runtime_dlls(app_dir: Path) -> None:
    """Copy MSVC runtime DLLs from the build Python next to the exes (helps targets without VC++ Redist)."""
    roots: list[Path] = []
    try:
        roots.append(Path(sys.executable).resolve().parent)
    except OSError:
        pass
    for base in (getattr(sys, "base_prefix", "") or "", getattr(sys, "prefix", "") or ""):
        if not base:
            continue
        p = Path(base).resolve()
        if p not in roots:
            roots.append(p)
        dlls = p / "DLLs"
        if dlls.is_dir() and dlls not in roots:
            roots.append(dlls)
    app_dir.mkdir(parents=True, exist_ok=True)
    for name in _MSVC_RUNTIME_DLLS:
        dest = app_dir / name
        if dest.is_file():
            continue
        for root in roots:
            src = root / name
            if src.is_file():
                shutil.copy2(str(src), str(dest))
                print(f"[OK] Bundled MSVC runtime: {name} <- {src}")
                break


def resolve_node_runtime_source() -> Path | None:
    env_src = os.getenv("NODE_RUNTIME_SOURCE", "").strip()
    if env_src:
        p = Path(env_src)
        if (p / "node.exe").exists():
            return p
    node_exe = shutil.which("node")
    if not node_exe:
        return None
    return Path(node_exe).resolve().parent


def copy_node_runtime() -> None:
    src = resolve_node_runtime_source()
    if not src:
        raise RuntimeError(
            "Node.js runtime source not found. Install Node.js or set NODE_RUNTIME_SOURCE."
        )
    dst = APP_DIR / "node_runtime"
    copy_tree(src, dst)
    if not (dst / "node.exe").exists():
        raise RuntimeError(f"node.exe not found after copy: {dst}")


def copy_optional_postgres_runtime() -> bool:
    env_src = os.getenv("POSTGRES_RUNTIME_DIR", "").strip()
    if not env_src:
        return False
    src = Path(env_src)
    if not (src / "bin" / "pg_ctl.exe").exists():
        raise RuntimeError(
            "POSTGRES_RUNTIME_DIR is set but invalid (missing bin/pg_ctl.exe)."
        )
    dst = APP_DIR / "postgres_runtime"
    copy_tree(src, dst)
    return True


def write_portable_readme(with_postgres: bool) -> None:
    pg_line = (
        "Bundled PostgreSQL: YES (auto-starts on first launch)."
        if with_postgres
        else "Bundled PostgreSQL: NO (app auto-falls back to SQLite)."
    )
    text = f"""GPT Intermediary - Portable Windows Bundle
==========================================

How to run on another PC:
1) Copy the WHOLE 'GPTIntermediary' folder to the target Windows PC.
2) Put your '.env' file next to GPTIntermediary.exe (or create one).
3) Double-click GPTIntermediary.exe.

This bundle includes:
- Python runtime (inside exe files)
- Node.js runtime (node_runtime/)
- Node dependencies (node_modules/)
- Backend/frontend code

{pg_line}

Notes:
- Keep the folder structure unchanged.
- Do not move only the exe file.
- Logs are written to logs/.
- If no valid DATABASE_URL is set, app uses SQLite at data/gptintermediary.sqlite3.
- Do NOT run from OneDrive, Dropbox, iCloud, or a network folder: sync breaks PostgreSQL and can corrupt DLLs (error 0xc000012f). Use a local path like C:\\Apps\\GPTIntermediary.
- If you still see missing vcruntime140.dll / MSVCP140, install "VC++ 2015-2022 x64" from Microsoft.

Smaller portable folder (optional build-time env vars):
- PORTABLE_INCLUDE_PUPPETEER_CHROME=1 — include Puppeteer's downloaded Chromium (large). Default OFF; without it, install Google Chrome on the target PC for WhatsApp Web, or set PUPPETEER_EXECUTABLE_PATH.
- PORTABLE_SKIP_DJANGO_EXE=1 — do not build or ship django.exe (omit if you do not use the Django tab).
- PORTABLE_SKIP_GMAIL_EXE=1 — do not build or ship get_gmail_token.exe (omit if Gmail OAuth was done elsewhere).

Optional build env vars:
- NODE_RUNTIME_SOURCE=C:\\path\\to\\nodejs\\folder (contains node.exe)
- POSTGRES_RUNTIME_DIR=C:\\path\\to\\portable-postgres (contains bin\\pg_ctl.exe)
"""
    (APP_DIR / "PORTABLE_README.txt").write_text(text, encoding="utf-8")


def main() -> int:
    if os.name != "nt":
        print("This build script is for Windows only.")
        return 1

    os.chdir(ROOT)
    ensure_pyinstaller()
    ensure_python_packages_for_build()
    if not _include_puppeteer_browser_downloads():
        print(
            "[*] Portable build omits Puppeteer's downloaded Chromium (saves ~0.3-1+ GB). "
            "Set PORTABLE_INCLUDE_PUPPETEER_CHROME=1 to bundle it, or install Chrome on the target PC for WhatsApp Web."
        )
    ensure_node_modules()

    safe_rmtree(PYI_WORK)
    safe_rmtree(PYI_SPEC)
    APP_DIR.mkdir(parents=True, exist_ok=True)

    backend_py = ROOT / "backend" / "python"
    django_app = ROOT / "backend" / "django_app"

    # Launcher: subprocess orchestration + dotenv + tkinter hooks
    pyinstaller_build(ROOT / "app.py", "GPTIntermediary")

    # FastAPI backend — static analysis often omits parts of the web stack in one-file builds
    backend_extras: list[str] = [
        "--paths",
        str(backend_py),
        *_collect_all_args(
            (
                "fastapi",
                "uvicorn",
                "starlette",
                "pydantic",
                "pydantic_core",
                "anyio",
                "httpx",
                "sqlalchemy",
                "alembic",
                "dotenv",
                "requests",
                "googleapiclient",
                "google_auth_oauthlib",
                "google_auth_httplib2",
                "passlib",
                "bcrypt",
                "jose",
                "cryptography",
                "multipart",
                "psycopg2",
                "asyncpg",
                "docx",
                "openpyxl",
                "PIL",
            )
        ),
    ]
    pyinstaller_build(backend_py / "main.py", "backend", backend_extras)

    chat_extras: list[str] = [
        "--paths",
        str(backend_py),
        *_collect_all_args(
            (
                "flask",
                "flask_cors",
                "werkzeug",
                "jinja2",
                "openai",
                "httpx",
                "requests",
                "dotenv",
            )
        ),
    ]
    pyinstaller_build(backend_py / "chat_server.py", "chat", chat_extras)

    django_extras: list[str] = [
        "--paths",
        str(django_app),
        "--paths",
        str(backend_py),
        *_collect_all_args(("django", "asgiref", "sqlparse", "dotenv")),
    ]
    skip_django = os.getenv("PORTABLE_SKIP_DJANGO_EXE", "").strip().lower() in ("1", "true", "yes")
    skip_gmail = os.getenv("PORTABLE_SKIP_GMAIL_EXE", "").strip().lower() in ("1", "true", "yes")

    if skip_django:
        print("[*] Skipping django.exe (PORTABLE_SKIP_DJANGO_EXE=1)")
    else:
        pyinstaller_build(django_app / "manage.py", "django", django_extras)

    if skip_gmail:
        print("[*] Skipping get_gmail_token.exe (PORTABLE_SKIP_GMAIL_EXE=1)")
    else:
        gmail_extras: list[str] = [
            "--paths",
            str(backend_py),
            *_collect_all_args(
                (
                    "google_auth_oauthlib",
                    "google_auth_httplib2",
                    "googleapiclient",
                    "google",
                    "dotenv",
                )
            ),
        ]
        pyinstaller_build(backend_py / "get_gmail_token.py", "get_gmail_token", gmail_extras)

    # Place all exes and runtime content under dist/GPTIntermediary
    built_exes = ["GPTIntermediary.exe", "backend.exe", "chat.exe"]
    if not skip_django:
        built_exes.append("django.exe")
    if not skip_gmail:
        built_exes.append("get_gmail_token.exe")
    for exe_name in built_exes:
        src = DIST_DIR / exe_name
        if src.exists():
            copy_file(src, APP_DIR / exe_name)
            src.unlink()

    # Remove leftovers from earlier full builds so "skip" flags actually shrink the folder.
    if skip_django:
        for p in (APP_DIR / "django.exe", DIST_DIR / "django.exe"):
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
    if skip_gmail:
        for p in (APP_DIR / "get_gmail_token.exe", DIST_DIR / "get_gmail_token.exe"):
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass

    print("[*] Bundling MSVC runtime DLLs from build Python...")
    bundle_msvc_runtime_dlls(APP_DIR)

    copy_tree(ROOT / "frontend", APP_DIR / "frontend")
    copy_tree(ROOT / "backend" / "node", APP_DIR / "backend" / "node")
    copy_app_node_modules(ROOT / "node_modules", APP_DIR / "node_modules")
    copy_node_runtime()

    if (ROOT / "run_get_gmail_token.bat").exists():
        copy_file(ROOT / "run_get_gmail_token.bat", APP_DIR / "run_get_gmail_token.bat")
    if (ROOT / ".env").exists():
        copy_file(ROOT / ".env", APP_DIR / ".env")
    elif (ROOT / ".env.example").exists():
        copy_file(ROOT / ".env.example", APP_DIR / ".env")

    (APP_DIR / "logs").mkdir(exist_ok=True)
    (APP_DIR / "data").mkdir(exist_ok=True)

    with_postgres = copy_optional_postgres_runtime()
    if not with_postgres:
        legacy_pg = APP_DIR / "postgres_runtime"
        if legacy_pg.is_dir():
            print("[*] Removing stale postgres_runtime/ (POSTGRES_RUNTIME_DIR not set for this build).")
            shutil.rmtree(legacy_pg, ignore_errors=True)

    write_portable_readme(with_postgres)

    print("\nBuild completed.")
    print(f"Portable folder: {APP_DIR}")
    print("Copy this entire folder to target machines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
