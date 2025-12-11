"""
Desktop Application Launcher for ChatGPT Assistant
Uses webview to create a standalone desktop app
Includes automatic Gmail token refresh
"""

import webview
import threading
import time
import subprocess
import sys
import os
import signal
import atexit

# Servers
backend_process = None
chat_process = None
django_process = None

DJANGO_PORT = 8001
DJANGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "django_app")

# Track if servers are running
servers_running = False

def refresh_gmail_tokens():
    """Refresh Gmail tokens by running get_gmail_token.py"""
    print("[*] Refreshing Gmail tokens...")
    print("[*] Note: This requires browser interaction. If you see no browser window,")
    print("[*]       run 'python get_gmail_token.py' manually to authorize Gmail access")
    try:
        result = subprocess.run(
            [sys.executable, "get_gmail_token.py"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print("[OK] Gmail tokens refreshed successfully!")
            return True
        else:
            print("[!] Gmail token refresh had issues (this is ok if you already have valid tokens)")
            print("[!] If you need new tokens, run: python get_gmail_token.py")
            return False
    except subprocess.TimeoutExpired:
        print("[!] Gmail token refresh timed out (continuing with existing tokens)")
        return False
    except Exception as e:
        print(f"[!] Gmail token refresh error (continuing anyway): {str(e)}")
        return False

def start_servers():
    """Start backend, chat, and Django servers"""
    global backend_process, chat_process, django_process, servers_running
    
    if servers_running:
        print("[!] Servers are already running!")
        return
    
    print("[*] Starting servers...")
    servers_running = True
    
    try:
        # Start backend server (main.py on port 8000)
        print("[*] Starting backend server (port 8000)...")
        backend_process = subprocess.Popen(
            [sys.executable, "main.py"],
            stdout=None,  # inherit stdout so errors are visible
            stderr=None,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        time.sleep(3)  # Wait for backend to start
        if backend_process.poll() is not None:
            print("[!] Backend server failed to start!")
            servers_running = False
            return
        print("[OK] Backend server started")
        
        # Start chat server (chat_server.py on port 5000)
        print("[*] Starting chat server (port 5000)...")
        # Try chat_server.py first, fallback to chat_server_simple.py
        chat_server_file = "chat_server.py"
        if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), chat_server_file)):
            chat_server_file = "chat_server_simple.py"
        
        chat_process = subprocess.Popen(
            [sys.executable, chat_server_file],
            stdout=None,
            stderr=None,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        time.sleep(2)  # Wait for chat server to start
        if chat_process.poll() is not None:
            print("[!] Chat server failed to start!")
            servers_running = False
            return
        print("[OK] Chat server started")

        # Start Django service (migrate + runserver)
        try:
            if os.path.isdir(DJANGO_DIR):
                print(f"[*] Applying Django migrations in {DJANGO_DIR}...")
                migrate_result = subprocess.run(
                    [sys.executable, "manage.py", "migrate", "--run-syncdb"],
                    cwd=DJANGO_DIR,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                if migrate_result.returncode != 0:
                    print("[!] Django migrate failed (continuing):")
                    print(migrate_result.stdout)
                    print(migrate_result.stderr)
                else:
                    print("[OK] Django migrate complete")

                print(f"[*] Starting Django dev server on port {DJANGO_PORT}...")
                django_process = subprocess.Popen(
                    [sys.executable, "manage.py", "runserver", str(DJANGO_PORT)],
                    stdout=None,
                    stderr=None,
                    cwd=DJANGO_DIR,
                )
                time.sleep(2)
                if django_process.poll() is not None:
                    print("[!] Django server failed to start!")
                else:
                    print("[OK] Django server started")
            else:
                print(f"[!] Django directory not found: {DJANGO_DIR} (skipping)")
        except Exception as e:
            print(f"[!] Django start error (skipping): {e}")

        print("[OK] All servers started successfully!")
        
    except Exception as e:
        print(f"[!] Error starting servers: {e}")
        import traceback
        traceback.print_exc()
        servers_running = False
        stop_servers()

def stop_servers():
    """Stop all servers"""
    global backend_process, chat_process, django_process, servers_running
    
    if not servers_running:
        return
    
    print("[*] Stopping servers...")
    servers_running = False
    
    # List of all processes to stop
    processes_to_stop = [
        (backend_process, "backend server", "port 8000"),
        (chat_process, "chat server", "port 5000"),
        (django_process, "Django server", f"port {DJANGO_PORT}")
    ]
    
    # Stop all processes
    for process, name, port_info in processes_to_stop:
        if process:
            try:
                print(f"[*] Terminating {name} ({port_info})...")
                process.terminate()
                process.wait(timeout=3)
                print(f"[OK] {name} stopped")
            except subprocess.TimeoutExpired:
                print(f"[*] Force killing {name}...")
                try:
                    process.kill()
                    process.wait(timeout=1)
                    print(f"[OK] {name} force killed")
                except Exception as e:
                    print(f"[!] Error killing {name}: {e}")
            except Exception as e:
                print(f"[!] Error stopping {name}: {e}")
    
    # Reset process variables
    backend_process = None
    chat_process = None
    django_process = None
    
    # Give ports time to be released
    time.sleep(1)
    print("[OK] All servers stopped!")

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
    
    try:
        # Refresh Gmail tokens first
        refresh_gmail_tokens()
        
        print("[*] Waiting 2 seconds before starting servers...")
        time.sleep(2)
        
        # Start servers in background thread
        server_thread = threading.Thread(target=start_servers, daemon=False)
        server_thread.start()
        
        # Wait for servers to be ready
        print("[*] Waiting for servers to initialize...")
        time.sleep(8)  # Wait for all servers to start
        
        # Check if servers started successfully
        if not servers_running:
            print("[!] Failed to start servers. Exiting...")
            return
        
        # Get the chat interface HTML path
        html_path = os.path.join(os.path.dirname(__file__), 'chat_interface.html')
        
        if not os.path.exists(html_path):
            print(f"[!] Error: {html_path} not found!")
            stop_servers()
            return
        
        print(f"[INFO] Loading HTML from: {html_path}")
        
        # Create desktop window
        window = webview.create_window(
            'ChatGPT Assistant - AI Automation',
            f'file://{html_path}',
            width=1200,
            height=800,
            resizable=True,
            frameless=False,
            easy_drag=True,
            background_color='#0a0e27'
        )
        
        # Start the GUI (this blocks until window is closed)
        print("[INFO] Starting webview GUI...")
        print("[INFO] Close the window or press Ctrl+C to stop all servers")
        webview.start(debug=False)
        
    except KeyboardInterrupt:
        print("\n[*] Keyboard interrupt received...")
    except Exception as e:
        print(f"[ERROR] Error in main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up servers when window closes or on error
        print("[INFO] Cleaning up...")
        stop_servers()

if __name__ == '__main__':
    main()
