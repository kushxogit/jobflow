import subprocess
import sys
import time
from pathlib import Path

def main():
    root_dir = Path(__file__).resolve().parent
    ui_dir = root_dir / "ui"

    print("=====================================")
    print("Starting JobFlow Services...")
    print("=====================================")

    print("--> Starting FastAPI Backend on port 8000...")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--reload", "--port", "8000"],
        cwd=root_dir
    )

    print("--> Starting Vite Frontend on port 5173...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=ui_dir
    )

    print("\nBoth services started! Press Ctrl+C at any time to shut them down.")
    print("Dashboard is available at: http://localhost:5173\n")

    try:
        # Keep the script running to catch Ctrl+C
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nCaught interrupt signal. Shutting down services...")
        backend.terminate()
        frontend.terminate()
        backend.wait()
        frontend.wait()
        print("Shutdown complete.")

if __name__ == "__main__":
    main()
