import os
import sys
import subprocess
import time
import signal
from pathlib import Path

def main():
    root_dir = Path(__file__).parent.absolute()
    frontend_dir = root_dir / "frontend"
    
    print("\n🚀 H2L Thesis Super Launcher (Full Stack Dev Mode)")
    print("====================================================")
    
    # 1. Environment Configuration
    print("⚙️  Configuring environment: ENABLING DENSE RUNTIME & RERANKER...")
    os.environ["H2L_SAFE_START"] = "false"
    os.environ["ENABLE_DENSE_RUNTIME"] = "true"
    os.environ["USE_RERANK"] = "true"
    os.environ["PYTHONPATH"] = str(root_dir)

    processes = []

    try:
        # 2. Start Backend Server (FastAPI)
        print("\n🖥️  [1/2] Starting Backend Server (Port 8000)...")
        backend_proc = subprocess.Popen(
            [sys.executable, "start.py"],
            cwd=root_dir,
            stdout=None, # Keep output in terminal
            stderr=None
        )
        processes.append(backend_proc)

        # Give backend a small head start
        time.sleep(2)

        # 3. Start Frontend Dev Server (Vite)
        print("\n🌐 [2/2] Starting Frontend Dev Server (Port 5173)...")
        frontend_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_dir,
            stdout=None,
            stderr=None
        )
        processes.append(frontend_proc)

        print("\n✅ All systems starting! Models are loading in the background.")
        print("👉 Frontend: http://localhost:5173")
        print("👉 API Health: http://localhost:8000/health")
        print("\n[Press Ctrl+C to stop both servers]")

        # Keep the script running
        while True:
            time.sleep(1)
            # Check if any process died unexpectedly
            if backend_proc.poll() is not None:
                print("\n❌ Backend server stopped unexpectedly.")
                break
            if frontend_proc.poll() is not None:
                print("\n❌ Frontend dev server stopped unexpectedly.")
                break

    except KeyboardInterrupt:
        print("\n\n👋 Stopping all services...")
    finally:
        # Graceful cleanup
        for proc in processes:
            if proc.poll() is None:
                # On Windows we might need a different approach, 
                # but on Mac/Linux signal.SIGTERM is good.
                proc.terminate()
        
        print("✨ Done.")

if __name__ == "__main__":
    main()
