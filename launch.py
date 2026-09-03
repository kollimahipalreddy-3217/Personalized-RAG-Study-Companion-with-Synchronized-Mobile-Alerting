"""
StudyEdge AI — Universal Local Engine & Application Launcher
Launches Ollama local model inference server and the StudyEdge Flask SocketIO app simultaneously.
"""

import os
import sys
import time
import socket
import subprocess
import webbrowser
import requests

OLLAMA_URL = "http://127.0.0.1:11434"
APP_PORT = 5000
APP_URL = f"http://localhost:{APP_PORT}"

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.8)
        return s.connect_ex((host, port)) == 0

def check_ollama_alive() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False

def start_ollama_service():
    print("[1/3] Checking Ollama AI Inference Engine...")
    if check_ollama_alive():
        print(" Ollama is already active on port 11434.")
        return True

    print("      Starting local 'ollama serve' in background...")
    try:
        # Check if ollama is available in PATH
        if sys.platform == "win32":
            subprocess.Popen(["ollama", "serve"], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"      [Warning] Could not spawn 'ollama serve' automatically: {e}")

    # Wait for Ollama to become ready
    for i in range(15):
        time.sleep(1)
        if check_ollama_alive():
            print(f" Ollama initialized and ready in {i+1}s.")
            return True
        print(f"      ... waiting for Ollama ({i+1}/15s)")

    print("      [Notice] Proceeding. If models fail to respond, run 'ollama serve' in another terminal.")
    return False

def inspect_installed_models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            print(f"      Installed Models: {', '.join(models) if models else 'None detected'}")
            return models
    except Exception:
        pass
    return []

def open_browser_delayed():
    time.sleep(1.8)
    try:
        webbrowser.open(APP_URL)
    except Exception:
        pass

def main():
    print("======================================================================")
    print("  PERSONALIZED RAG STUDY COMPANION WITH SYNCHRONIZED MOBILE ALERTING")
    print("  Application Interface: StudyEdge AI")
    print("======================================================================")
    print()

    # 1. Start or verify Ollama
    start_ollama_service()
    inspect_installed_models()
    print()

    # 2. Launch browser in a background thread
    print(f"[2/3] Preparing Web Studio Interface at {APP_URL}...")
    import threading
    threading.Thread(target=open_browser_delayed, daemon=True).start()

    # 3. Launch Flask SocketIO Application
    print(f"[3/3] Starting StudyEdge AI Main Server on port {APP_PORT}...")
    print("----------------------------------------------------------------------")
    print(f"  Web Dashboard:  {APP_URL}")
    print(f"  Mobile Web App: {APP_URL}/mobile")
    print("----------------------------------------------------------------------")
    print("  Press CTRL+C to stop the server.")
    print()

    # Run app.py in foreground
    try:
        import app
        # If app.py is run directly via import / socketio.run:
        app.socketio.run(app.app, host="0.0.0.0", port=APP_PORT, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print("\n[StudyEdge AI] Server shutting down cleanly. Goodbye!")
    except Exception as e:
        # Fallback to subprocess
        subprocess.run([sys.executable, "app.py"])

if __name__ == "__main__":
    main()
