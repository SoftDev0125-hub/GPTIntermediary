#!/usr/bin/env python3
"""
Build Windows executables that run on **other** PCs without Python or Node installed.

Run from the project root on your **development / build** machine (Windows, 64-bit Python):

  python build.py

That machine must have: Node.js on PATH, `npm install` in the repo root, and network
access the first time (PyInstaller is installed automatically if needed).

The **output** is under `dist/`. Copy the whole `dist` folder to another computer; that
computer does not need Python, Node, or npm. See `dist/PORTABLE_README.txt` after a build.

For best compatibility of the built exes across Windows versions, use Python 3.11 or 3.12
from https://www.python.org/downloads/windows/ when running this script.
"""
import os
import subprocess
import sys
from pathlib import Path


def _venv_python(root: str) -> Path | None:
    """Prefer project venv so PyInstaller bundles the same packages as `pip install -r requirements.txt`."""
    if sys.platform == "win32":
        p = Path(root) / "venv" / "Scripts" / "python.exe"
    else:
        p = Path(root) / "venv" / "bin" / "python"
    return p if p.is_file() else None


def _maybe_reexec_with_venv(root: str) -> None:
    if getattr(sys, "frozen", False):
        return
    venv_py = _venv_python(root)
    if not venv_py:
        return
    try:
        if Path(sys.executable).resolve() == venv_py.resolve():
            return
    except OSError:
        return
    print(f"[*] Using project virtual environment: {venv_py}")
    os.execv(str(venv_py), [str(venv_py), __file__, *sys.argv[1:]])


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    _maybe_reexec_with_venv(root)
    script = os.path.join(root, 'tools', 'build_exe.py')
    if not os.path.isfile(script):
        print(f"Missing build script: {script}")
        return 1
    return subprocess.call([sys.executable, script], cwd=root)


if __name__ == '__main__':
    raise SystemExit(main())
