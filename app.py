import os
import sys
import time
import signal
import atexit
import subprocess
import threading
import shutil
from pathlib import Path


def _maybe_reexec_with_project_venv():
    """If a local venv exists, run under it so subprocesses use the same interpreter."""
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parent
    if sys.platform == "win32":
        venv_py = root / "venv" / "Scripts" / "python.exe"
    else:
        venv_py = root / "venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    try:
        if Path(sys.executable).resolve() == venv_py.resolve():
            return
    except OSError:
        return
    print(f"[*] Using project virtual environment: {venv_py}")
    os.execv(str(venv_py), [str(venv_py)] + sys.argv)


_maybe_reexec_with_project_venv()

# Load project root .env so spawned processes inherit env vars
try:
    from dotenv import load_dotenv
    _app_root = Path(__file__).resolve().parent
    load_dotenv(_app_root / '.env')
except Exception:
    pass

# Try to import psutil for better process management
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("[!] Warning: psutil not installed. Process cleanup may be less reliable.")
    print("[!] Install with: pip install psutil")

# Global variables to track server processes
backend_process = None
chat_process = None
django_process = None
whatsapp_node_process = None
telegram_node_process = None
slack_node_process = None
servers_running = False
backend_log = None
chat_log = None
django_log = None
whatsapp_log = None
telegram_log = None
slack_log = None

# Set when start_servers() finishes (success, early exit, or error) so main can open UI after full startup
server_startup_done_event = threading.Event()

# Django server configuration
DJANGO_DIR = os.path.join("backend", "django_app")
DJANGO_PORT = 8001

def _is_frozen():
    """True when running as a PyInstaller bundle (standalone exe)."""
    return getattr(sys, 'frozen', False)


def _get_script_dir():
    """Project/installation root: exe directory when frozen, else directory of app.py."""
    if _is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_node_executable(script_dir):
    """
    Path to node.exe: bundled (frozen build), PATH, then standard Windows install dirs.
    Cursor/IDE shells often omit Node from PATH even when Node.js is installed.
    """
    frozen = _is_frozen()
    if frozen:
        bundled = os.path.join(script_dir, "node_runtime", "node.exe")
        if os.path.isfile(bundled):
            return bundled
    found = shutil.which("node")
    if found:
        return found
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        for candidate in (
            os.path.join(pf, "nodejs", "node.exe"),
            os.path.join(pfx86, "nodejs", "node.exe"),
            os.path.join(local, "Programs", "nodejs", "node.exe") if local else "",
        ):
            if candidate and os.path.isfile(candidate):
                return candidate
    return "node"


def _print_log_tail(log_path, max_lines=35):
    """Print last max_lines of a log file so user sees why a server exited."""
    if not log_path or not os.path.isfile(log_path):
        return
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        if not lines:
            return
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        print("[!] Last lines of log:")
        for line in tail:
            print("    " + line.rstrip())
    except Exception as e:
        print(f"[!] Could not read log: {e}")


def _wait_for_node_server(proc, log_path, service_name, port, max_attempts=20, health_url=None):
    """
    Wait until a Node child listens on port (optional HTTP health_url), or it exits.
    Returns True if ready, False if process died, None if still running but not verified in time.
    """
    import socket
    import urllib.request
    for attempt in range(max_attempts):
        time.sleep(1)
        if proc.poll() is not None:
            # stop_servers() sets servers_running False and kills children — not a startup failure
            if not servers_running:
                return None
            print(f"[!] {service_name} failed to start (process exited).")
            _print_log_tail(log_path)
            print(f"[!] Full log: {log_path}")
            return False
        try:
            if health_url:
                urllib.request.urlopen(health_url, timeout=2)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                ok = sock.connect_ex(("localhost", port)) == 0
                sock.close()
                if not ok:
                    raise OSError("port not accepting")
            return True
        except Exception:
            if (attempt + 1) % 5 == 0:
                print(f"[*] Waiting for {service_name} on port {port}... ({attempt + 1}s)")
    if proc.poll() is None:
        print(
            f"[!] {service_name} is running but not verified on port {port} yet "
            f"(see {log_path})."
        )
        return None
    return False


def start_servers():
    """Start all backend servers in separate processes"""
    global backend_process, chat_process, django_process, whatsapp_node_process, telegram_node_process, slack_node_process, servers_running
    global backend_log, chat_log, django_log, whatsapp_log, telegram_log, slack_log
    
    # Make sure we're in the right directory (exe dir when frozen)
    script_dir = _get_script_dir()
    os.chdir(script_dir)

    backend_py_dir = os.path.join(script_dir, "backend", "python")
    frozen = _is_frozen()
    backend_exe = os.path.join(script_dir, "backend.exe") if frozen else None
    chat_exe = os.path.join(script_dir, "chat.exe") if frozen else None
    node_exe = _resolve_node_executable(script_dir)
    if node_exe != "node" and os.path.isfile(node_exe):
        print(f"[*] Using Node.js: {node_exe}")

    server_startup_done_event.clear()
    servers_running = True
    log_dir = os.path.join(script_dir, 'logs')
    print("[*] Starting all backend servers...")
    print(f"[*] Working directory: {os.getcwd()}")
    if frozen:
        print(f"[*] Logs (if servers fail): {log_dir}")
    
    try:
        # Start backend server (backend/python/main.py on port 8000)
        print("[*] Starting backend server (main.py on port 8000)...")
        try:
            # Ensure port 8000 is free (kill any existing process using it)
            print("[*] Checking if port 8000 is available...")
            try:
                if kill_process_by_port(8000):
                    print("[*] Killed existing process on port 8000")
                    time.sleep(1)
            except Exception as e:
                print(f"[!] Error while ensuring port 8000 is free: {e}")

            # Create log file for backend server output
            os.makedirs(log_dir, exist_ok=True)
            os.makedirs(log_dir, exist_ok=True)
            backend_log = open(os.path.join(log_dir, 'backend_server.log'), 'w', encoding='utf-8')
            
            backend_cmd = [backend_exe] if frozen and backend_exe and os.path.isfile(backend_exe) else [sys.executable, "main.py"]
            backend_cwd = script_dir if frozen else backend_py_dir
            backend_process = subprocess.Popen(
                backend_cmd,
                stdout=backend_log,  # Write to log file
                stderr=backend_log,  # Write errors to log file
                cwd=backend_cwd,
                # Prevent child from inheriting debug/reloader environment variables
                env={k: v for k, v in os.environ.items() if k not in ('DEBUG', 'FLASK_DEBUG', 'FLASK_ENV')},
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            time.sleep(2)  # Reduced initial wait - verification loop will handle longer waits
            backend_log.flush()  # Ensure log is written
            
            # Verify server is actually responding with process health checks
            import urllib.request
            import socket
            max_retries = 15  # Increased from 10 to 15 to allow more time for service initialization
            backend_ready = False
            log_path = os.path.join(log_dir, 'backend_server.log')
            
            for i in range(max_retries):
                # Check if process is still running (important during long waits)
                if backend_process.poll() is not None:
                    backend_log.close()
                    # Process died, read the log file to see what happened
                    try:
                        with open(log_path, 'r', encoding='utf-8') as f:
                            log_content = f.read()
                            if log_content:
                                print(f"[!] Backend server process died!")
                                print(f"[!] Last 500 chars of log: {log_content[-500:]}")
                            else:
                                print(f"[!] Backend server process died! (no log output)")
                    except Exception as log_error:
                        print(f"[!] Backend server process died! Could not read log: {log_error}")
                    print(f"[!] Full log available at: {log_path}")
                    servers_running = False
                    return
                
                try:
                    response = urllib.request.urlopen('http://localhost:8000/', timeout=2)  # Reduced timeout for faster checks
                    print("[OK] Backend server started and responding on http://localhost:8000")
                    backend_ready = True
                    break
                except (urllib.error.URLError, socket.timeout, ConnectionRefusedError):
                    if i < max_retries - 1:
                        # Print progress every 3 attempts
                        if (i + 1) % 3 == 0:
                            print(f"[*] Waiting for backend server to respond... ({i+1}/{max_retries})")
                            # Show recent log output if available (for debugging)
                            try:
                                with open(log_path, 'r', encoding='utf-8') as f:
                                    log_lines = f.readlines()
                                    if log_lines:
                                        recent_logs = ''.join(log_lines[-3:]).strip()
                                        if recent_logs and len(recent_logs) < 200:
                                            print(f"    Recent log: {recent_logs}")
                            except:
                                pass
                        time.sleep(1)
                    else:
                        # Final attempt failed - check if process is still alive
                        if backend_process.poll() is None:
                            print("[!] Warning: Backend server process is running but not responding yet")
                            print("[!] It may still be initializing services.")
                        else:
                            print("[!] Error: Backend server process died!")
                        print(f"[!] Check logs/backend_server.log for details: {log_path}")
                        print("[!] Continuing anyway...")
                        break
                except Exception as e:
                    print(f"[!] Warning: Could not verify backend server: {e}")
                    break
            
            # Keep log file open for the process lifetime
            # backend_log will be closed when process is stopped
        except Exception as e:
            print(f"[!] Error starting backend server: {e}")
            servers_running = False
            return
        
        # Start chat server (backend/python/chat_server.py on port 5000, or chat.exe when frozen)
        print("[*] Starting chat server (port 5000)...")
        # When frozen we run chat.exe (no .py file on disk); when not frozen we need the .py file
        if frozen and chat_exe and os.path.isfile(chat_exe):
            chat_server_file = "chat_server.py"  # only for error messages
        else:
            chat_server_file = "chat_server.py"
            if not os.path.exists(os.path.join(backend_py_dir, chat_server_file)):
                chat_server_file = "chat_server_simple.py"
                if not os.path.exists(os.path.join(backend_py_dir, chat_server_file)):
                    print("[!] No chat server file found (looking for chat_server.py or chat_server_simple.py)")
                    servers_running = False
                    return
        
        try:
            # Avoid stdout/stderr PIPE without readers (can deadlock/hang long-running servers on Windows)
            try:
                log_dir = os.path.join(script_dir, 'logs')
                os.makedirs(log_dir, exist_ok=True)
                chat_log = open(os.path.join(log_dir, 'chat_server.log'), 'a', encoding='utf-8')
            except Exception:
                chat_log = None
            chat_log_path = None
            if chat_log:
                chat_log_path = os.path.join(log_dir, 'chat_server.log')
                chat_log.flush()  # Ensure log file is ready
            
            chat_cmd = [chat_exe] if frozen and chat_exe and os.path.isfile(chat_exe) else [sys.executable, chat_server_file]
            chat_cwd = script_dir if frozen else backend_py_dir
            chat_process = subprocess.Popen(
                chat_cmd,
                stdout=chat_log if chat_log else subprocess.DEVNULL,
                stderr=chat_log if chat_log else subprocess.DEVNULL,
                cwd=chat_cwd,
                # Ensure child process doesn't inherit debug/reloader env vars
                env={k: v for k, v in os.environ.items() if k not in ('DEBUG', 'FLASK_DEBUG', 'FLASK_ENV')},
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            time.sleep(1)  # initial short wait

            # If the process exited quickly, it may be the reloader parent; check port before failing
            if chat_process.poll() is not None:
                # Wait up to a short timeout for the server to start and listen on port 5000
                import socket
                chat_port_ready = False
                for retry in range(8):
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex(('localhost', 5000))
                        sock.close()
                        if result == 0:
                            chat_port_ready = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)

                if not chat_port_ready:
                    print("[!] Chat server failed to start!")
                    exit_code = chat_process.returncode
                    print(f"[!] Exit code: {exit_code}")
                
                # Try to read error from log file
                if chat_log_path and os.path.exists(chat_log_path):
                    try:
                        # Logs may contain non-UTF8 bytes on Windows; never crash while reading them.
                        with open(chat_log_path, 'r', encoding='utf-8', errors='replace') as f:
                            log_content = f.read()
                            if log_content:
                                # Show last 500 characters of log
                                error_snippet = log_content[-500:] if len(log_content) > 500 else log_content
                                print(f"[!] Error from log file:")
                                print(f"    {error_snippet}")
                            else:
                                print(f"[!] Log file is empty. Check if {chat_server_file} exists and is executable.")
                    except Exception as log_error:
                        print(f"[!] Could not read log file: {log_error}")
                else:
                    print(f"[!] Could not find log file. Check if {chat_server_file} exists in {backend_py_dir}")
                    print(f"[!] Full path checked: {os.path.join(backend_py_dir, chat_server_file)}")
                
                print(f"[!] Check logs/chat_server.log for full error details: {chat_log_path}")
                servers_running = False
                return
            print("[OK] Chat server started on http://localhost:5000")
        except Exception as e:
            print(f"[!] Error starting chat server: {e}")
            servers_running = False
            return
        
        # Start Django server if django_app directory exists or django.exe (frozen)
        try:
            django_exe = os.path.join(script_dir, "django.exe") if frozen and os.path.isfile(os.path.join(script_dir, "django.exe")) else None
            django_dir_abs = os.path.abspath(os.path.join(script_dir, DJANGO_DIR))
            manage_py = os.path.join(django_dir_abs, "manage.py")
            start_django = (frozen and django_exe) or (os.path.exists(DJANGO_DIR) and os.path.isdir(DJANGO_DIR) and os.path.exists(manage_py))
            if start_django:
                print(f"[*] Starting Django server on port {DJANGO_PORT}...")
                try:
                    try:
                        log_dir = os.path.join(script_dir, 'logs')
                        os.makedirs(log_dir, exist_ok=True)
                        django_log = open(os.path.join(log_dir, 'django_server.log'), 'a', encoding='utf-8')
                    except Exception:
                        django_log = None
                    env = os.environ.copy()
                    env["DJANGO_PORT"] = str(DJANGO_PORT)
                    if frozen and django_exe:
                        django_process = subprocess.Popen(
                            [django_exe],
                            stdout=django_log if django_log else subprocess.DEVNULL,
                            stderr=django_log if django_log else subprocess.DEVNULL,
                            cwd=script_dir,
                            env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        )
                    else:
                        django_process = subprocess.Popen(
                            [sys.executable, "manage.py", "runserver", f"127.0.0.1:{DJANGO_PORT}", "--noreload"],
                            stdout=django_log if django_log else subprocess.DEVNULL,
                            stderr=django_log if django_log else subprocess.DEVNULL,
                            cwd=django_dir_abs,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        )
                    time.sleep(3)
                    if django_process.poll() is not None:
                        print("[!] Django server failed to start!")
                        if django_log:
                            try:
                                django_log.seek(0)
                                err = django_log.read(500)
                                if err:
                                    print(f"[!] Log: {err[-500:]}")
                            except Exception:
                                pass
                    else:
                        print(f"[OK] Django server started on http://localhost:{DJANGO_PORT}")
                except Exception as e:
                    print(f"[!] Error starting Django server: {e}")
            elif not frozen:
                if not os.path.exists(DJANGO_DIR) or not os.path.isdir(DJANGO_DIR):
                    print(f"[!] Django directory not found: {DJANGO_DIR} (skipping)")
                else:
                    print(f"[!] manage.py not found in {DJANGO_DIR}")
        except Exception as e:
            print(f"[!] Django start error (skipping): {e}")
        
        # Start Node.js WhatsApp server (whatsapp_server.js on port 3000)
        print("[*] Starting Node.js WhatsApp server (port 3000)...")
        whatsapp_server_file = os.path.join("backend", "node", "whatsapp_server.js")
        if os.path.exists(os.path.join(script_dir, whatsapp_server_file)):
            try:
                # Check if port 3000 is already in use and kill the process
                print("[*] Checking if port 3000 is available...")
                if kill_process_by_port(3000):
                    print("[*] Killed existing process on port 3000")
                    time.sleep(1)  # Wait a moment for port to be released
                
                # Check if Node.js is available (use bundled node_exe when frozen)
                try:
                    node_check = subprocess.run(
                        [node_exe, '--version'],
                        capture_output=True,
                        timeout=2,
                        cwd=script_dir
                    )
                    if node_check.returncode != 0:
                        raise FileNotFoundError("Node.js not found")
                    print(f"[*] Node.js version: {node_check.stdout.decode('utf-8', errors='ignore').strip()}")
                except FileNotFoundError:
                    print("[!] Node.js not found. WhatsApp server will not start.")
                    if frozen:
                        print(f"[!] Place Node.js in: {os.path.join(script_dir, 'node_runtime')}")
                        print("[!] (Copy node.exe and DLLs from https://nodejs.org/ Windows 64-bit .zip)")
                    else:
                        print("[!] Install Node.js from https://nodejs.org/")
                    whatsapp_node_process = None
                else:
                    # Log to file (avoid PIPE without readers which can hang servers)
                    try:
                        log_dir = os.path.join(script_dir, 'logs')
                        os.makedirs(log_dir, exist_ok=True)
                        whatsapp_log = open(os.path.join(log_dir, 'whatsapp_server.log'), 'a', encoding='utf-8')
                    except Exception:
                        whatsapp_log = None
                    wa_proc = subprocess.Popen(
                        [node_exe, whatsapp_server_file],
                        stdout=(whatsapp_log if whatsapp_log else subprocess.DEVNULL),
                        stderr=(whatsapp_log if whatsapp_log else subprocess.DEVNULL),
                        cwd=script_dir,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    whatsapp_node_process = wa_proc
                    # Wait for WhatsApp server to bind to port (Node + whatsapp-web.js require can be slow)
                    import socket
                    whatsapp_ready = False
                    for attempt in range(12):  # up to 12 seconds
                        time.sleep(1)
                        if wa_proc.poll() is not None:
                            print("[!] WhatsApp Node.js server process exited!")
                            _print_log_tail(os.path.join(log_dir, 'whatsapp_server.log'))
                            print(f"[!] Full log: {os.path.join(log_dir, 'whatsapp_server.log')}")
                            whatsapp_node_process = None
                            break
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1)
                            result = sock.connect_ex(('localhost', 3000))
                            sock.close()
                            if result == 0:
                                print("[OK] WhatsApp Node.js server started on http://localhost:3000")
                                whatsapp_ready = True
                                break
                        except Exception:
                            pass
                        if (attempt + 1) % 3 == 0:
                            print(f"[*] Waiting for WhatsApp server to listen on port 3000... ({attempt + 1}s)")
                    if not whatsapp_ready and wa_proc.poll() is None:
                        print("[!] WhatsApp server process started but not listening on port 3000 yet (may still be loading). Check logs/whatsapp_server.log")
            except Exception as e:
                print(f"[!] Error starting WhatsApp Node.js server: {e}")
                whatsapp_node_process = None
        else:
            print(f"[!] WhatsApp server file not found: {whatsapp_server_file} (skipping)")
        
        # Start Node.js Telegram server (telegram_server.js on port 3001)
        print("[*] Starting Node.js Telegram server (port 3001)...")
        telegram_server_file = os.path.join("backend", "node", "telegram_server.js")
        if os.path.exists(os.path.join(script_dir, telegram_server_file)):
            try:
                print("[*] Ensuring port 3001 is free for Telegram server...")
                if kill_process_by_port(3001):
                    print("[*] Freed port 3001 (previous Telegram or stray process)")
                time.sleep(1)

                # Check if Node.js is available (reuse check from WhatsApp or check again)
                try:
                    if 'node_check' not in locals() or node_check is None or node_check.returncode != 0:
                        node_check = subprocess.run(
                            [node_exe, '--version'],
                            capture_output=True,
                            timeout=2,
                            cwd=script_dir
                        )
                        if node_check.returncode != 0:
                            raise FileNotFoundError("Node.js not found")
                except FileNotFoundError:
                    print("[!] Node.js not found. Telegram server will not start.")
                    if frozen and telegram_node_process is None:
                        print(f"[!] Place Node.js in: {os.path.join(script_dir, 'node_runtime')}")
                    telegram_node_process = None
                else:
                    # Log to file (avoid PIPE without readers which can hang servers)
                    try:
                        log_dir = os.path.join(script_dir, 'logs')
                        os.makedirs(log_dir, exist_ok=True)
                        telegram_log = open(os.path.join(log_dir, 'telegram_server.log'), 'a', encoding='utf-8')
                    except Exception:
                        telegram_log = None
                    tg_proc = subprocess.Popen(
                        [node_exe, telegram_server_file],
                        stdout=(telegram_log if telegram_log else subprocess.DEVNULL),
                        stderr=(telegram_log if telegram_log else subprocess.DEVNULL),
                        cwd=script_dir,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    telegram_node_process = tg_proc
                    tg_log_path = os.path.join(log_dir, "telegram_server.log")
                    tg_ready = _wait_for_node_server(
                        tg_proc,
                        tg_log_path,
                        "Telegram Node.js server",
                        3001,
                        max_attempts=25,
                        health_url="http://localhost:3001/health",
                    )
                    if tg_ready is False:
                        telegram_node_process = None
                    elif tg_ready is True:
                        print("[OK] Telegram Node.js server started on http://localhost:3001")
                    elif tg_ready is None and not servers_running:
                        telegram_node_process = None
            except Exception as e:
                print(f"[!] Error starting Telegram Node.js server: {e}")
                telegram_node_process = None
        else:
            print(f"[!] Telegram server file not found: {telegram_server_file} (skipping)")
        
        # Start Node.js Slack server (slack_server.js on port 3002)
        print("[*] Starting Node.js Slack server (port 3002)...")
        slack_server_file = os.path.join("backend", "node", "slack_server.js")
        if os.path.exists(os.path.join(script_dir, slack_server_file)):
            try:
                print("[*] Ensuring port 3002 is free for Slack server...")
                if kill_process_by_port(3002):
                    print("[*] Freed port 3002 (previous Slack or stray process)")
                time.sleep(1)

                # Check if Node.js is available (reuse check from WhatsApp/Telegram or check again)
                try:
                    if 'node_check' not in locals() or node_check is None or node_check.returncode != 0:
                        node_check = subprocess.run(
                            [node_exe, '--version'],
                            capture_output=True,
                            timeout=2,
                            cwd=script_dir
                        )
                        if node_check.returncode != 0:
                            raise FileNotFoundError("Node.js not found")
                except FileNotFoundError:
                    print("[!] Node.js not found. Slack server will not start.")
                    if frozen:
                        print(f"[!] Place Node.js in: {os.path.join(script_dir, 'node_runtime')}")
                    slack_node_process = None
                else:
                    # Log to file (avoid PIPE without readers which can hang servers)
                    try:
                        log_dir = os.path.join(script_dir, 'logs')
                        os.makedirs(log_dir, exist_ok=True)
                        slack_log = open(os.path.join(log_dir, 'slack_server.log'), 'a', encoding='utf-8')
                    except Exception:
                        slack_log = None
                    sl_proc = subprocess.Popen(
                        [node_exe, slack_server_file],
                        stdout=(slack_log if slack_log else subprocess.DEVNULL),
                        stderr=(slack_log if slack_log else subprocess.DEVNULL),
                        cwd=script_dir,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    slack_node_process = sl_proc
                    sl_log_path = os.path.join(log_dir, "slack_server.log")
                    sl_ready = _wait_for_node_server(
                        sl_proc,
                        sl_log_path,
                        "Slack Node.js server",
                        3002,
                        max_attempts=25,
                        health_url="http://localhost:3002/health",
                    )
                    if sl_ready is False:
                        slack_node_process = None
                    elif sl_ready is True:
                        print("[OK] Slack Node.js server started on http://localhost:3002")
                    elif sl_ready is None and not servers_running:
                        slack_node_process = None
            except Exception as e:
                print(f"[!] Error starting Slack Node.js server: {e}")
                slack_node_process = None
        else:
            print(f"[!] Slack server file not found: {slack_server_file} (skipping)")
        
        print("[OK] Startup complete.")
        print("[*] Server status:")
        print(f"    - Backend API: http://localhost:8000")
        print(f"    - Chat Server: http://localhost:5000")
        if whatsapp_node_process and whatsapp_node_process.poll() is None:
            print(f"    - WhatsApp Server: http://localhost:3000")
        if telegram_node_process and telegram_node_process.poll() is None:
            print(f"    - Telegram Server: http://localhost:3001")
        if slack_node_process and slack_node_process.poll() is None:
            print(f"    - Slack Server: http://localhost:3002")
        if django_process and django_process.poll() is None:
            print(f"    - Django Server: http://localhost:{DJANGO_PORT}")
        print("[*] You can now use the application interface.")
        
    except Exception as e:
        print(f"[!] Error starting servers: {e}")
        import traceback
        traceback.print_exc()
        servers_running = False
        stop_servers(startup_cleanup=True)
    finally:
        server_startup_done_event.set()

def kill_process_by_port(port):
    """Kill process using a specific port (Windows/Linux compatible)"""
    killed_any = False
    
    # Try psutil first if available (more reliable)
    if HAS_PSUTIL:
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    connections = proc.net_connections(kind='inet')
                    for conn in connections:
                        if conn.laddr and conn.laddr.port == port:
                            print(f"[*] Found process {proc.info['name']} (PID: {proc.info['pid']}) using port {port}")
                            try:
                                proc.kill()
                                proc.wait(timeout=2)
                                print(f"[OK] Killed process {proc.info['pid']} on port {port}")
                                killed_any = True
                                time.sleep(0.5)  # Wait for port to be released
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                                pass
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, AttributeError):
                    continue
            if killed_any:
                return True
        except Exception as e:
            print(f"[!] Error killing process on port {port} (psutil method): {e}")
    
    # Fallback: Use netstat and taskkill on Windows, or lsof and kill on Unix
    try:
        if sys.platform == 'win32':
            # Use netstat to find PID, then taskkill
            # Try multiple times to catch all processes
            for attempt in range(3):
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                found_any = False
                pids_to_kill = set()  # Use set to avoid killing same PID multiple times
                
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    # Check for both IPv4 and IPv6 formats, and LISTENING state
                    if f':{port}' in line and 'LISTENING' in line:
                        # Parse the line - format is: PROTO  Local Address  Foreign Address  State  PID
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            # Validate PID is numeric
                            try:
                                int(pid)
                                pids_to_kill.add(pid)
                            except ValueError:
                                continue
                
                # Kill all found PIDs
                for pid in pids_to_kill:
                    try:
                        kill_result = subprocess.run(
                            ['taskkill', '/F', '/PID', pid], 
                            capture_output=True, 
                            timeout=3
                        )
                        if kill_result.returncode == 0:
                            print(f"[OK] Killed process {pid} on port {port}")
                            killed_any = True
                            found_any = True
                            time.sleep(0.5)  # Wait for port to be released
                        else:
                            # Check if process doesn't exist (already killed)
                            error_msg = kill_result.stderr.decode('utf-8', errors='ignore') if kill_result.stderr else ''
                            if 'not found' not in error_msg.lower():
                                print(f"[!] Failed to kill process {pid}: {error_msg.strip()}")
                    except Exception as e:
                        print(f"[!] Exception killing PID {pid}: {e}")
                
                if not found_any:
                    break  # No more processes found
        else:
            # Unix-like: use lsof to find PID, then kill
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(['kill', '-9', pid], timeout=2, capture_output=True)
                        print(f"[OK] Killed process {pid} on port {port}")
                        killed_any = True
                    except:
                        pass
    except Exception as e:
        print(f"[!] Error killing process on port {port} (fallback method): {e}")
    return killed_any

def stop_servers(startup_cleanup=False):
    """Stop all servers. Use startup_cleanup=True when aborting after a failed start_servers()."""
    global backend_process, chat_process, django_process, whatsapp_node_process, telegram_node_process, slack_node_process, servers_running
    global backend_log, chat_log, django_log, whatsapp_log, telegram_log, slack_log
    
    if not servers_running:
        # Even if servers_running is False, try to kill processes by port
        if startup_cleanup:
            print("[*] Freeing server ports after startup error...")
        else:
            print("[*] Attempting to stop any remaining server processes...")
        kill_process_by_port(8000)  # Backend
        kill_process_by_port(5000)  # Chat
        kill_process_by_port(3000)  # WhatsApp Node.js
        kill_process_by_port(3001)  # Telegram Node.js
        kill_process_by_port(3002)  # Slack Node.js
        kill_process_by_port(DJANGO_PORT)  # Django
        return
    
    print("[*] Stopping servers...")
    servers_running = False
    
    # Close log files if they exist
    try:
        if backend_log:
            backend_log.close()
            backend_log = None
    except:
        pass
    try:
        if chat_log:
            chat_log.close()
            chat_log = None
    except:
        pass
    try:
        if django_log:
            django_log.close()
            django_log = None
    except:
        pass
    try:
        if whatsapp_log:
            whatsapp_log.close()
            whatsapp_log = None
    except:
        pass
    try:
        if telegram_log:
            telegram_log.close()
            telegram_log = None
    except:
        pass
    try:
        if slack_log:
            slack_log.close()
            slack_log = None
    except:
        pass
    
    # List of all processes to stop
    processes_to_stop = [
        (backend_process, "backend server", 8000),
        (chat_process, "chat server", 5000),
        (whatsapp_node_process, "WhatsApp Node.js server", 3000),
        (telegram_node_process, "Telegram Node.js server", 3001),
        (slack_node_process, "Slack Node.js server", 3002),
        (django_process, "Django server", DJANGO_PORT)
    ]
    
    # Stop all processes
    for process, name, port in processes_to_stop:
        if process:
            try:
                print(f"[*] Terminating {name} (port {port})...")
                # On Windows, terminate() might not work, so try kill() directly
                if sys.platform == 'win32':
                    if HAS_PSUTIL:
                        try:
                            # Try to get the process tree and kill children too
                            parent = psutil.Process(process.pid)
                            children = parent.children(recursive=True)
                            for child in children:
                                try:
                                    child.kill()
                                except:
                                    pass
                            parent.kill()
                            process.wait(timeout=2)
                            print(f"[OK] {name} stopped")
                        except (psutil.NoSuchProcess, subprocess.TimeoutExpired):
                            # Fallback to subprocess methods
                            process.kill()
                            try:
                                process.wait(timeout=2)
                            except:
                                pass
                            print(f"[OK] {name} stopped")
                        except Exception as e:
                            print(f"[!] Error stopping {name}: {e}")
                            # Try killing by port as fallback
                            kill_process_by_port(port)
                    else:
                        # No psutil, just kill directly
                        process.kill()
                        try:
                            process.wait(timeout=2)
                        except:
                            pass
                        print(f"[OK] {name} stopped")
                else:
                    # On Unix-like systems, use terminate first
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        print(f"[OK] {name} stopped")
                    except subprocess.TimeoutExpired:
                        print(f"[*] Force killing {name}...")
                        process.kill()
                        process.wait(timeout=1)
                        print(f"[OK] {name} force killed")
            except Exception as e:
                print(f"[!] Error stopping {name}: {e}")
                # Try killing by port as fallback
                kill_process_by_port(port)
    
    # Also try killing by port in case process objects are invalid
    print("[*] Checking for any remaining processes on server ports...")
    kill_process_by_port(8000)  # Backend
    kill_process_by_port(5000)  # Chat
    kill_process_by_port(3000)  # WhatsApp Node.js
    kill_process_by_port(3001)  # Telegram Node.js
    kill_process_by_port(3002)  # Slack Node.js
    kill_process_by_port(DJANGO_PORT)  # Django
    
    # Reset process variables
    backend_process = None
    chat_process = None
    whatsapp_node_process = None
    telegram_node_process = None
    slack_node_process = None
    django_process = None
    
    print("[OK] All servers stopped")

def open_browser(url):
    """Open URL in default browser (cross-platform)"""
    # Try multiple methods to ensure browser opens
    methods = []
    
    # Method 1: webbrowser module (most common)
    try:
        import webbrowser
        methods.append(('webbrowser', lambda: webbrowser.open(url)))
    except ImportError:
        pass
    
    # Method 2: Windows startfile (Windows-specific, very reliable)
    if sys.platform == 'win32':
        methods.append(('Windows startfile', lambda: os.startfile(url)))
    
    # Method 3: Direct command execution (fallback)
    if sys.platform == 'win32':
        methods.append(('Windows cmd', lambda: subprocess.Popen(['cmd', '/c', 'start', '', url], shell=False)))
    elif sys.platform == 'darwin':  # macOS
        methods.append(('macOS open', lambda: subprocess.Popen(['open', url])))
    else:  # Linux
        methods.append(('xdg-open', lambda: subprocess.Popen(['xdg-open', url])))
    
    # Try each method until one succeeds
    for method_name, method_func in methods:
        try:
            method_func()
            print(f"[OK] Opened {url} in browser (using {method_name})")
            time.sleep(0.5)  # Small delay to ensure browser starts
            return True
        except Exception as e:
            continue
    
    # If all methods failed
    print(f"[!] Failed to open browser automatically.")
    print(f"[!] Please manually open: {url}")
    return False


def _chromium_app_user_data_dir():
    """Isolated profile so --app runs as its own instance (avoids instant launcher exit + handoff)."""
    base = _get_script_dir()
    d = os.path.join(base, "data", "chromium_app_profile")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _windows_chromium_exe_paths():
    """Edge / Chrome locations for standalone app windows (not a normal browser tab)."""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    # User-level Edge/Chrome installs first (common on locked-down or per-user setups)
    paths = []
    if local:
        paths.extend(
            [
                os.path.join(local, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            ]
        )
    paths.extend(
        [
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pfx86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pfx86, "Google", "Chrome", "Application", "chrome.exe"),
        ]
    )
    custom = os.environ.get("CHROMIUM_APP_EXE", "").strip()
    if custom and os.path.isfile(custom):
        paths.insert(0, custom)
    seen = set()
    out = []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            if os.path.isfile(p):
                out.append(p)
    return out


def open_windows_chromium_app_window(url, width=1200, height=800, x=None, y=None):
    """
    Open Edge or Chrome in application mode (dedicated window, minimal chrome).
    Used when pywebview is unavailable (e.g. Python 3.14: pythonnet does not build yet).
    Returns subprocess.Popen on success, else None.
    """
    if sys.platform != "win32":
        return None
    profile = _chromium_app_user_data_dir()
    # Dedicated user-data-dir keeps a persistent browser process for this app instead of
    # a stub launcher that exits immediately (which used to shut down all servers).
    common = [
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--app={url}",
        f"--window-size={int(width)},{int(height)}",
    ]
    if x is not None and y is not None:
        common.append(f"--window-position={int(x)},{int(y)}")
    for exe in _windows_chromium_exe_paths():
        try:
            return subprocess.Popen([exe] + common)
        except OSError:
            continue
    return None


def _wait_for_chromium_app_process(proc, label="application window"):
    """
    Edge/Chrome often start a short-lived launcher that exits while the real window stays open.
    Wait until the monitored process exits *or* treat an immediate clean exit as a handoff and
    keep servers running until Ctrl+C here.
    """
    print(f"[*] Close the {label} or press Ctrl+C here to stop all servers.")
    saw_running = False
    for _ in range(25):
        if proc.poll() is None:
            saw_running = True
            break
        time.sleep(0.2)
    try:
        if saw_running:
            while proc.poll() is None:
                time.sleep(0.5)
            print(f"\n[*] {label} closed")
        else:
            code = proc.poll()
            if code == 0:
                print(
                    "\n[*] Browser launcher exited; if the app window is still open, use it. "
                    "Press Ctrl+C here when you want to stop the servers."
                )
            else:
                print(f"\n[!] Browser exited early (code {code}). Press Ctrl+C to stop servers.")
            while servers_running:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\n[*] Interrupt received...")
        if saw_running and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    print("[*] Stopping all servers...")
    stop_servers()
    print("[*] All servers stopped. Goodbye!")


def _windows_desktop_shell_unavailable(app_url):
    """
    No Edge/Chrome --app and no pywebview: keep servers up; do not open a normal browser tab
    (this project is intended to run as a desktop app).
    """
    print("[!] Could not start a desktop application window (Edge/Chrome --app or pywebview).")
    print("[!] Install or repair Microsoft Edge, or install Google Chrome.")
    print("[!] Optional: set CHROMIUM_APP_EXE in .env to the full path of msedge.exe or chrome.exe.")
    print("[!] For embedded WebView2 via Python, use Python 3.11 or 3.12 and: pip install pywebview")
    print(f"[!] Servers are running at: {app_url}")
    print("[*] Press Ctrl+C in this console to stop all servers.")
    try:
        while servers_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping all servers...")
        stop_servers()
        print("[*] All servers stopped. Goodbye!")


def _try_windows_chromium_app_shell(app_url, window_width, window_height, x=None, y=None):
    """Launch Edge/Chrome in app mode; block until closed. Returns True if launched."""
    proc = open_windows_chromium_app_window(app_url, window_width, window_height, x, y)
    if not proc:
        return False
    print(
        "[*] Desktop app window: Edge or Chrome (application mode). "
        "Tip: DESKTOP_SHELL=webview uses pywebview first when installed."
    )
    _wait_for_chromium_app_process(proc, "application window")
    return True


def signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl+C)"""
    print("\n[*] Interrupt signal received...")
    stop_servers()
    sys.exit(0)

def main():
    """Main application entry point"""
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Register atexit only if servers are still running (avoids duplicate cleanup after normal UI exit).
    def _atexit_stop_if_needed():
        if (
            servers_running
            or backend_process is not None
            or chat_process is not None
            or django_process is not None
            or whatsapp_node_process is not None
            or telegram_node_process is not None
            or slack_node_process is not None
        ):
            stop_servers()

    atexit.register(_atexit_stop_if_needed)
    
    # Start all servers in a separate thread
    print("=" * 60)
    print("[*] GPT Intermediary - Starting Application")
    print("=" * 60)
    
    try:
        # Start servers in a thread to keep them running
        server_thread = threading.Thread(target=start_servers, daemon=True)
        server_thread.start()
        
        # Wait until start_servers() finishes (backend + Node children + health checks)
        print("[*] Waiting for background server startup to complete...")
        if not server_startup_done_event.wait(timeout=180):
            print("[!] Startup phase exceeded 180s; continuing with health checks...")
        
        # Check if servers started successfully
        if not servers_running:
            print("[!] Failed to start servers. Exiting...")
            print("[!] Check the error messages above to see which server failed.")
            print("[!] You can try starting servers manually:")
            print("[!]   - Backend: python backend/python/main.py")
            print("[!]   - Chat: python backend/python/chat_server.py")
            return
        
        # Verify backend server is actually running with retries
        print("[*] Verifying backend server is responding...")
        import urllib.request
        import socket
        max_retries = 20  # Increased to allow more time for Telegram initialization timeout
        backend_ready = False
        for i in range(max_retries):
            try:
                response = urllib.request.urlopen('http://localhost:8000/', timeout=3)  # Increased timeout slightly
                print("[OK] Backend server is responding on http://localhost:8000")
                backend_ready = True
                break
            except (urllib.error.URLError, socket.timeout, ConnectionRefusedError) as e:
                if i < max_retries - 1:
                    if (i + 1) % 3 == 0:  # Print every 3 attempts
                        print(f"[*] Waiting for backend server... ({i+1}/{max_retries})")
                    time.sleep(1)
                else:
                    print(f"[!] Warning: Backend server may not be ready: {e}")
                    print("[!] The window will open, but some features may not work.")
                    print("[!] Check if main.py started successfully in the background.")
                    print("[!] You may need to start it manually: python backend/python/main.py")
                    print("[!] Check logs/backend_server.log for startup errors")
            except Exception as e:
                print(f"[!] Warning: Could not verify backend server: {e}")
                break
        
        if not backend_ready:
            print("[!] Backend server verification failed after multiple attempts.")
            print("[!] Continuing anyway - the app window will open.")
            print("[!] If features don't work, check if the backend server is running.")
        
        # Verify chat server is ready before opening browser
        print("[*] Verifying chat server is ready...")
        chat_ready = False
        for i in range(10):
            try:
                response = urllib.request.urlopen('http://localhost:5000/', timeout=2)
                print("[OK] Chat server is ready on http://localhost:5000")
                chat_ready = True
                break
            except (urllib.error.URLError, socket.timeout, ConnectionRefusedError):
                if i < 9:
                    time.sleep(1)
                else:
                    print("[!] Chat server not ready, but opening browser anyway...")
        
        # Open the application through the chat server (which serves login page at root)
        # This ensures the login page is shown first, then redirects to chat_interface.html after login
        
        # Check if running in server/VPS mode
        is_server = os.environ.get("VPS") == "true" or os.environ.get("IS_SERVER") == "true"
        domain = os.environ.get("DOMAIN", None)
        use_https = os.environ.get("USE_HTTPS", "false").lower() == "true"
        
        # Determine app URL based on environment
        if is_server and domain:
            # VPS with domain: Use domain (assumes reverse proxy handles ports)
            protocol = "https" if use_https else "http"
            app_url = f"{protocol}://{domain}/"
        else:
            # Local development: Use localhost
            app_url = "http://localhost:5000/"
        
        if is_server:
            # Server/VPS mode: No GUI, browser-only access
            print("=" * 60)
            print("[*] Running in SERVER MODE (VPS/Container)")
            print("[*] Application is running and accessible via browser")
            
            if domain:
                print(f"[*] Domain access: {app_url}")
                print(f"[*] Access from your browser: {app_url}")
            else:
                print(f"[*] Local access: http://localhost:5000/")
                # Try to get server IP for remote access
                try:
                    import socket
                    # Get the actual network IP (not 127.0.0.1)
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    server_ip = s.getsockname()[0]
                    s.close()
                    print(f"[*] Network access: http://{server_ip}:5000")
                except Exception:
                    try:
                        # Fallback method
                        hostname = socket.gethostname()
                        server_ip = socket.gethostbyname(hostname)
                        if server_ip != "127.0.0.1":
                            print(f"[*] Network access: http://{server_ip}:5000")
                    except Exception:
                        pass
            
            print("[*] Press Ctrl+C to stop all servers and exit")
            print("=" * 60)
            
            # Keep servers running until interrupted
            try:
                while servers_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n[*] Stopping all servers...")
                stop_servers()
                print("[*] All servers stopped. Goodbye!")
        else:
            # Desktop mode: dedicated app window only (Edge/Chrome --app and/or pywebview), not a normal browser tab.
            print("=" * 60)
            print("[*] Starting as desktop application (app window, not a browser tab)...")
            print(f"[*] Application URL: {app_url}")
            print("[*] You will see the login page first.")
            print("[*] Close the app window or press Ctrl+C here to stop all servers.")
            print("=" * 60)

            window_width, window_height, x, y = 1200, 800, None, None
            try:
                import tkinter as tk
                root = tk.Tk()
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                root.destroy()
                default_width = 1200
                default_height = 800
                window_width = min(default_width, int(screen_width * 0.7))
                window_height = min(default_height, int(screen_height * 0.7))
                window_width = max(800, window_width)
                window_height = max(600, window_height)
                x = (screen_width - window_width) // 2
                y = (screen_height - window_height) // 2
            except Exception:
                pass

            shell_pref = os.environ.get("DESKTOP_SHELL", "").strip().lower()
            prefer_webview_first = shell_pref == "webview"

            def _run_pywebview():
                import webview

                webview.create_window(
                    "GPT Intermediary",
                    app_url,
                    width=window_width,
                    height=window_height,
                    x=x,
                    y=y,
                    resizable=True,
                    min_size=(800, 600),
                    fullscreen=False,
                )
                webview.start(debug=False)
                print("\n[*] Application window closed")
                print("[*] Stopping all servers...")
                stop_servers()
                print("[*] All servers stopped. Goodbye!")

            if sys.platform == "win32":
                if prefer_webview_first:
                    try:
                        _run_pywebview()
                    except ImportError:
                        if not _try_windows_chromium_app_shell(
                            app_url, window_width, window_height, x, y
                        ):
                            _windows_desktop_shell_unavailable(app_url)
                    except Exception as e:
                        print(f"[!] pywebview failed: {e}")
                        print("[*] Trying Edge/Chrome application window...")
                        if not _try_windows_chromium_app_shell(
                            app_url, window_width, window_height, x, y
                        ):
                            _windows_desktop_shell_unavailable(app_url)
                else:
                    if _try_windows_chromium_app_shell(
                        app_url, window_width, window_height, x, y
                    ):
                        pass
                    else:
                        try:
                            _run_pywebview()
                        except ImportError:
                            _windows_desktop_shell_unavailable(app_url)
                        except Exception as e:
                            print(f"[!] pywebview failed: {e}")
                            _windows_desktop_shell_unavailable(app_url)
            else:
                try:
                    _run_pywebview()
                except ImportError:
                    print("[!] Install with: pip install pywebview")
                    print("[*] Opening in default browser (non-Windows)...")
                    browser_opened = open_browser(app_url)
                    if browser_opened:
                        print("[*] Browser opened successfully!")
                    else:
                        print(f"[!] Could not open browser automatically.")
                        print(f"[!] Please manually open: {app_url}")
                    print("[*] Servers are running. Press Ctrl+C to stop all servers and exit")
                    try:
                        while servers_running:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        print("\n[*] Stopping all servers...")
                        stop_servers()
                        print("[*] All servers stopped. Goodbye!")
                except Exception as e:
                    print(f"[!] Error creating webview window: {e}")
                    print("[*] Falling back to browser...")
                    browser_opened = open_browser(app_url)
                    if browser_opened:
                        print("[*] Browser opened successfully!")
                    else:
                        print(f"[!] Could not open browser automatically.")
                        print(f"[!] Please manually open: {app_url}")
                    print("[*] Servers are running. Press Ctrl+C to stop all servers and exit")
                    try:
                        while servers_running:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        print("\n[*] Stopping all servers...")
                        stop_servers()
                        print("[*] All servers stopped. Goodbye!")
        
    except KeyboardInterrupt:
        print("\n[*] Keyboard interrupt received")
    except Exception as e:
        print(f"[!] Application error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Avoid a second full shutdown (and duplicate port-kill messages) after a normal UI exit.
        if (
            servers_running
            or backend_process is not None
            or chat_process is not None
            or django_process is not None
            or whatsapp_node_process is not None
            or telegram_node_process is not None
            or slack_node_process is not None
        ):
            print("\n[*] Shutting down...")
            stop_servers()
        print("[*] Goodbye!")

if __name__ == "__main__":
    main()
