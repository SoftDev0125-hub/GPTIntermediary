"""
Simple launcher without OpenAI - Direct backend calls
"""

import requests

BACKEND_URL = "http://localhost:8000"

def launch_app(app_name):
    """Launch an application"""
    response = requests.post(f"{BACKEND_URL}/api/app/launch", json={"app_name": app_name})
    if response.status_code == 200:
        print(f"✅ Launched {app_name}")
    else:
        print(f"❌ Failed: {response.text}")

if __name__ == "__main__":
    print("Simple App Launcher - No OpenAI required")
    print("=" * 50)
    
    while True:
        app = input("\nEnter app name to launch (or 'quit' to exit): ").strip()
        if app.lower() == 'quit':
            break
        if app:
            launch_app(app)
    
    print("\nGoodbye!")
