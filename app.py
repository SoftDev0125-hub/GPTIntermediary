"""
Desktop Application Launcher for ChatGPT Assistant
Uses webview to create a standalone desktop app
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

def start_servers():
    """Start backend and chat servers"""
    global backend_process, chat_process
    
    print("[*] Starting servers...")
    
    # Start backend server
    backend_process = subprocess.Popen(
        [sys.executable, "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    time.sleep(3)  # Wait for backend to start
    
    # Start chat server
    chat_process = subprocess.Popen(
        [sys.executable, "chat_server_simple.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    time.sleep(2)  # Wait for chat server to start
    print("[OK] Servers started!")

def stop_servers():
    """Stop all servers"""
    global backend_process, chat_process
    
    print("[*] Stopping servers...")
    if backend_process:
        backend_process.terminate()
    if chat_process:
        chat_process.terminate()
    print("[OK] Servers stopped!")

def main():
    """Main application entry point"""
    
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
