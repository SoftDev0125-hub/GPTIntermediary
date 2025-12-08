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

# Servers
backend_process = None
chat_process = None
django_process = None

DJANGO_PORT = 8001
DJANGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "django_app")

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
    global backend_process, chat_process, django_process
    
    print("[*] Starting servers...")
    
    # Start backend server
    backend_process = subprocess.Popen(
        [sys.executable, "main.py"],
        stdout=None,  # inherit stdout so errors are visible
        stderr=None,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    time.sleep(3)  # Wait for backend to start
    
    # Start chat server
    chat_process = subprocess.Popen(
        [sys.executable, "chat_server_simple.py"],
        stdout=None,
        stderr=None,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    time.sleep(2)  # Wait for chat server to start

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
        else:
            print(f"[!] Django directory not found: {DJANGO_DIR} (skipping)")
    except Exception as e:
        print(f"[!] Django start error (skipping): {e}")

    print("[OK] Servers started!")

def stop_servers():
    """Stop all servers"""
    global backend_process, chat_process, django_process
    
    print("[*] Stopping servers...")
    
    # Stop backend server (port 8000)
    if backend_process:
        try:
            print("[*] Terminating backend server (port 8000)...")
            backend_process.terminate()
            backend_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("[*] Force killing backend server...")
            backend_process.kill()
            backend_process.wait()
    
    # Stop chat server (port 5000)
    if chat_process:
        try:
            print("[*] Terminating chat server (port 5000)...")
            chat_process.terminate()
            chat_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("[*] Force killing chat server...")
            chat_process.kill()
            chat_process.wait()

    # Stop Django server (port 8001)
    if django_process:
        try:
            print(f"[*] Terminating Django server (port {DJANGO_PORT})...")
            django_process.terminate()
            django_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("[*] Force killing Django server...")
            django_process.kill()
            django_process.wait()
    
    # Give ports time to be released
    time.sleep(1)
    print("[OK] Servers stopped!")

def main():
    """Main application entry point"""
    
    # Refresh Gmail tokens first
    refresh_gmail_tokens()
    
    print("[*] Waiting 2 seconds before starting servers...")
    time.sleep(2)
    
    # Start servers in background thread
    server_thread = threading.Thread(target=start_servers, daemon=True)
    server_thread.start()
    
    # Wait for servers to be ready
    time.sleep(8)  # Increased wait time
    
    # Get the chat interface HTML path
    html_path = os.path.join(os.path.dirname(__file__), 'chat_interface.html')
    
    print(f"[INFO] Loading HTML from: {html_path}")
    print(f"[INFO] File exists: {os.path.exists(html_path)}")
    
    # Create desktop window
    try:
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
        
        # Start the GUI
        print("[INFO] Starting webview GUI...")
        webview.start()
    except Exception as e:
        print(f"[ERROR] Error starting webview: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up servers when window closes
        print("[INFO] Cleaning up...")
        stop_servers()

if __name__ == '__main__':
    main()
