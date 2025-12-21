import os
import sys
import time
import signal
import atexit
import subprocess
import threading

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
servers_running = False
backend_log = None

# Django server configuration
DJANGO_DIR = "django_app"
DJANGO_PORT = 8001

def start_servers():
    """Start all backend servers in separate processes"""
    global backend_process, chat_process, django_process, whatsapp_node_process, telegram_node_process, servers_running
    
    # Make sure we're in the right directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    servers_running = True
    print("[*] Starting all backend servers...")
    print(f"[*] Working directory: {os.getcwd()}")
    
    try:
        # Start backend server (main.py on port 8000)
        print("[*] Starting backend server (main.py on port 8000)...")
        try:
            # Create log file for backend server output
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            global backend_log
            backend_log = open(os.path.join(log_dir, 'backend_server.log'), 'w', encoding='utf-8')
            
            backend_process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=backend_log,  # Write to log file
                stderr=backend_log,  # Write errors to log file
                cwd=os.path.dirname(os.path.abspath(__file__)),
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
        
        # Start chat server (chat_server.py on port 5000)
        print("[*] Starting chat server (port 5000)...")
        # Try chat_server.py first, fallback to chat_server_simple.py
        chat_server_file = "chat_server.py"
        if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), chat_server_file)):
            chat_server_file = "chat_server_simple.py"
            if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), chat_server_file)):
                print("[!] No chat server file found (looking for chat_server.py or chat_server_simple.py)")
                servers_running = False
                return
        
        try:
            chat_process = subprocess.Popen(
                [sys.executable, chat_server_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            time.sleep(3)  # Wait for chat server to start
            if chat_process.poll() is not None:
                stdout, stderr = chat_process.communicate()
                print("[!] Chat server failed to start!")
                if stderr:
                    print(f"[!] Error: {stderr.decode('utf-8', errors='ignore')[:200]}")
                servers_running = False
                return
            print("[OK] Chat server started on http://localhost:5000")
        except Exception as e:
            print(f"[!] Error starting chat server: {e}")
            servers_running = False
            return
        
        # Start Django server if django_app directory exists
        try:
            if os.path.exists(DJANGO_DIR) and os.path.isdir(DJANGO_DIR):
                print(f"[*] Starting Django server on port {DJANGO_PORT}...")
                # Get absolute path to manage.py
                django_dir_abs = os.path.abspath(DJANGO_DIR)
                manage_py = os.path.join(django_dir_abs, "manage.py")
                if os.path.exists(manage_py):
                    try:
                        django_process = subprocess.Popen(
                            [sys.executable, "manage.py", "runserver", f"127.0.0.1:{DJANGO_PORT}", "--noreload"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            cwd=django_dir_abs,  # Use absolute path for cwd
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        )
                        time.sleep(3)
                        if django_process.poll() is not None:
                            stdout, stderr = django_process.communicate()
                            print("[!] Django server failed to start!")
                            if stderr:
                                print(f"[!] Error: {stderr.decode('utf-8', errors='ignore')[:200]}")
                        else:
                            print(f"[OK] Django server started on http://localhost:{DJANGO_PORT}")
                    except Exception as e:
                        print(f"[!] Error starting Django server: {e}")
                else:
                    print(f"[!] manage.py not found in {DJANGO_DIR}")
            else:
                print(f"[!] Django directory not found: {DJANGO_DIR} (skipping)")
        except Exception as e:
            print(f"[!] Django start error (skipping): {e}")
        
        # Start Node.js WhatsApp server (whatsapp_server.js on port 3000)
        print("[*] Starting Node.js WhatsApp server (port 3000)...")
        whatsapp_server_file = "whatsapp_server.js"
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), whatsapp_server_file)):
            try:
                # Check if port 3000 is already in use and kill the process
                print("[*] Checking if port 3000 is available...")
                if kill_process_by_port(3000):
                    print("[*] Killed existing process on port 3000")
                    time.sleep(1)  # Wait a moment for port to be released
                
                # Check if Node.js is available
                try:
                    node_check = subprocess.run(
                        ['node', '--version'],
                        capture_output=True,
                        timeout=2
                    )
                    if node_check.returncode != 0:
                        raise FileNotFoundError("Node.js not found")
                    print(f"[*] Node.js version: {node_check.stdout.decode('utf-8', errors='ignore').strip()}")
                except FileNotFoundError:
                    print("[!] Node.js not found. WhatsApp server will not start.")
                    print("[!] Install Node.js from https://nodejs.org/")
                    whatsapp_node_process = None
                else:
                    whatsapp_node_process = subprocess.Popen(
                        ['node', whatsapp_server_file],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=os.path.dirname(os.path.abspath(__file__)),
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    time.sleep(3)  # Wait for WhatsApp server to start
                    if whatsapp_node_process.poll() is not None:
                        stdout, stderr = whatsapp_node_process.communicate()
                        print("[!] WhatsApp Node.js server failed to start!")
                        if stdout:
                            stdout_msg = stdout.decode('utf-8', errors='ignore')[:500]
                            if stdout_msg.strip():
                                print(f"[!] stdout: {stdout_msg}")
                        if stderr:
                            error_msg = stderr.decode('utf-8', errors='ignore')[:500]
                            print(f"[!] stderr: {error_msg}")
                        whatsapp_node_process = None
                    else:
                        # Verify server is actually listening
                        import socket
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1)
                            result = sock.connect_ex(('localhost', 3000))
                            sock.close()
                            if result == 0:
                                print("[OK] WhatsApp Node.js server started on http://localhost:3000")
                            else:
                                print("[!] WhatsApp server process started but not listening on port 3000")
                        except Exception as e:
                            print(f"[!] Could not verify WhatsApp server: {e}")
            except Exception as e:
                print(f"[!] Error starting WhatsApp Node.js server: {e}")
                whatsapp_node_process = None
        else:
            print(f"[!] WhatsApp server file not found: {whatsapp_server_file} (skipping)")
        
        # Start Node.js Telegram server (telegram_server.js on port 3001)
        print("[*] Starting Node.js Telegram server (port 3001)...")
        telegram_server_file = "telegram_server.js"
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), telegram_server_file)):
            try:
                # Check if port 3001 is already in use and kill the process
                print("[*] Checking if port 3001 is available...")
                if kill_process_by_port(3001):
                    print("[*] Killed existing process on port 3001")
                    time.sleep(1)  # Wait a moment for port to be released
                
                # Check if Node.js is available (reuse check from WhatsApp or check again)
                try:
                    if 'node_check' not in locals() or node_check is None or node_check.returncode != 0:
                        node_check = subprocess.run(
                            ['node', '--version'],
                            capture_output=True,
                            timeout=2
                        )
                        if node_check.returncode != 0:
                            raise FileNotFoundError("Node.js not found")
                except FileNotFoundError:
                    print("[!] Node.js not found. Telegram server will not start.")
                    telegram_node_process = None
                else:
                    telegram_node_process = subprocess.Popen(
                        ['node', telegram_server_file],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=os.path.dirname(os.path.abspath(__file__)),
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    time.sleep(3)  # Wait for Telegram server to start
                    if telegram_node_process.poll() is not None:
                        stdout, stderr = telegram_node_process.communicate()
                        print("[!] Telegram Node.js server failed to start!")
                        if stdout:
                            stdout_msg = stdout.decode('utf-8', errors='ignore')[:500]
                            if stdout_msg.strip():
                                print(f"[!] stdout: {stdout_msg}")
                        if stderr:
                            error_msg = stderr.decode('utf-8', errors='ignore')[:500]
                            print(f"[!] stderr: {error_msg}")
                        telegram_node_process = None
                    else:
                        # Verify server is actually listening
                        import socket
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1)
                            result = sock.connect_ex(('localhost', 3001))
                            sock.close()
                            if result == 0:
                                print("[OK] Telegram Node.js server started on http://localhost:3001")
                            else:
                                print("[!] Telegram server process started but not listening on port 3001")
                        except Exception as e:
                            print(f"[!] Could not verify Telegram server: {e}")
            except Exception as e:
                print(f"[!] Error starting Telegram Node.js server: {e}")
                telegram_node_process = None
        else:
            print(f"[!] Telegram server file not found: {telegram_server_file} (skipping)")
        
        print("[OK] All servers started successfully!")
        print("[*] Server status:")
        print(f"    - Backend API: http://localhost:8000")
        print(f"    - Chat Server: http://localhost:5000")
        if whatsapp_node_process and whatsapp_node_process.poll() is None:
            print(f"    - WhatsApp Server: http://localhost:3000")
        if telegram_node_process and telegram_node_process.poll() is None:
            print(f"    - Telegram Server: http://localhost:3001")
        if django_process and django_process.poll() is None:
            print(f"    - Django Server: http://localhost:{DJANGO_PORT}")
        print("[*] You can now use the application interface.")
        
    except Exception as e:
        print(f"[!] Error starting servers: {e}")
        import traceback
        traceback.print_exc()
        servers_running = False
        stop_servers()

def kill_process_by_port(port):
    """Kill process using a specific port (Windows/Linux compatible)"""
    if not HAS_PSUTIL:
        # Fallback: Use netstat and taskkill on Windows, or lsof and kill on Unix
        try:
            if sys.platform == 'win32':
                # Use netstat to find PID, then taskkill
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            try:
                                subprocess.run(['taskkill', '/F', '/PID', pid], 
                                             capture_output=True, timeout=2)
                                print(f"[OK] Killed process {pid} on port {port}")
                                return True
                            except:
                                pass
            else:
                # Unix-like: use lsof to find PID, then kill
                result = subprocess.run(
                    ['lsof', '-ti', f':{port}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    pid = result.stdout.strip()
                    subprocess.run(['kill', '-9', pid], timeout=2)
                    print(f"[OK] Killed process {pid} on port {port}")
                    return True
        except Exception as e:
            print(f"[!] Error killing process on port {port} (fallback method): {e}")
        return False
    
    # Use psutil if available
    try:
        for proc in psutil.process_iter(['pid', 'name', 'connections']):
            try:
                for conn in proc.info['connections'] or []:
                    if conn.laddr.port == port:
                        print(f"[*] Found process {proc.info['name']} (PID: {proc.info['pid']}) using port {port}")
                        proc.kill()
                        proc.wait(timeout=2)
                        print(f"[OK] Killed process on port {port}")
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        print(f"[!] Error killing process on port {port}: {e}")
    return False

def stop_servers():
    """Stop all servers"""
    global backend_process, chat_process, django_process, whatsapp_node_process, telegram_node_process, servers_running, backend_log
    
    if not servers_running:
        # Even if servers_running is False, try to kill processes by port
        print("[*] Attempting to stop any remaining server processes...")
        kill_process_by_port(8000)  # Backend
        kill_process_by_port(5000)  # Chat
        kill_process_by_port(3000)  # WhatsApp Node.js
        kill_process_by_port(3001)  # Telegram Node.js
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
    
    # List of all processes to stop
    processes_to_stop = [
        (backend_process, "backend server", 8000),
        (chat_process, "chat server", 5000),
        (whatsapp_node_process, "WhatsApp Node.js server", 3000),
        (telegram_node_process, "Telegram Node.js server", 3001),
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
    kill_process_by_port(DJANGO_PORT)  # Django
    
    # Reset process variables
    backend_process = None
    chat_process = None
    whatsapp_node_process = None
    telegram_node_process = None
    django_process = None
    
    print("[OK] All servers stopped")

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
    
    # Register atexit handler to ensure cleanup
    atexit.register(stop_servers)
    
    # Start all servers in a separate thread
    print("=" * 60)
    print("[*] GPT Intermediary - Starting Application")
    print("=" * 60)
    
    try:
        # Start servers in a thread to keep them running
        server_thread = threading.Thread(target=start_servers, daemon=True)
        server_thread.start()
        
        # Wait for servers to be ready
        print("[*] Waiting for servers to initialize...")
        time.sleep(10)  # Wait for all servers to start (increased wait time)
        
        # Check if servers started successfully
        if not servers_running:
            print("[!] Failed to start servers. Exiting...")
            print("[!] Check the error messages above to see which server failed.")
            print("[!] You can try starting servers manually:")
            print("[!]   - Backend: python main.py")
            print("[!]   - Chat: python chat_server.py")
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
                    print("[!] You may need to start it manually: python main.py")
                    print("[!] Check logs/backend_server.log for startup errors")
            except Exception as e:
                print(f"[!] Warning: Could not verify backend server: {e}")
                break
        
        if not backend_ready:
            print("[!] Backend server verification failed after multiple attempts.")
            print("[!] Continuing anyway - the app window will open.")
            print("[!] If features don't work, check if the backend server is running.")
        
        # Get the login page HTML path
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'login.html')
        html_path = os.path.normpath(html_path)
        
        if not os.path.exists(html_path):
            print(f"[!] Error: {html_path} not found!")
            print(f"[!] Current directory: {os.getcwd()}")
            print(f"[!] Script directory: {os.path.dirname(os.path.abspath(__file__))}")
            stop_servers()
            return
        
        print(f"[*] Opening login page: {html_path}")
        print("[*] The application window should open now...")
        print("[*] Press Ctrl+C to stop all servers and exit")
        print("=" * 60)
        
        # Try to create and show the webview window
        try:
            import webview
            
            # Create the window
            window = webview.create_window(
                'GPT Intermediary',
                html_path,
                width=1400,
                height=900,
                resizable=True
            )
            
            # Start the webview (this blocks until window is closed)
            webview.start()
            
            print("\n[*] Application window closed")
            # IMPORTANT: Do NOT stop servers when the window closes.
            # Users often run the UI in an external browser, and pywebview can close unexpectedly
            # (missing runtime, crash, etc.). Servers should keep running until Ctrl+C.
            print("[*] Servers will continue running in the background.")
            print("[*] Press Ctrl+C to stop servers and exit")

            # Best-effort: open in default browser so the user still has a UI after webview closes
            try:
                import webbrowser
                webbrowser.open(f'file:///{html_path}')
            except Exception:
                pass

            # Keep the main thread alive until Ctrl+C
            try:
                while servers_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            
        except ImportError:
            print("[!] pywebview not installed. Opening in default browser instead...")
            import webbrowser
            webbrowser.open(f'file:///{html_path}')
            print("[*] Opened in browser. Servers will continue running.")
            print("[*] Press Ctrl+C to stop servers and exit")
            
            # Keep the main thread alive
            try:
                while servers_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
                
        except Exception as e:
            print(f"[!] Error creating webview window: {e}")
            print("[*] Attempting to open in default browser instead...")
            import webbrowser
            webbrowser.open(f'file:///{html_path}')
            print("[*] Opened in browser. Servers will continue running.")
            print("[*] Press Ctrl+C to stop servers and exit")
            
            # Keep the main thread alive
            try:
                while servers_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        
    except KeyboardInterrupt:
        print("\n[*] Keyboard interrupt received")
    except Exception as e:
        print(f"[!] Application error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[*] Shutting down...")
        stop_servers()
        print("[*] Goodbye!")

if __name__ == "__main__":
    main()
