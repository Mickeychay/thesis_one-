import os
import sys
import subprocess
import time
import socket
import signal
import uvicorn
from pathlib import Path

def kill_port(port):
    """Attempt to gracefully stop processes listening on a port (Mac/Linux)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print("   lsof not found; skipping automatic port cleanup.")
        return
    except Exception as exc:
        print(f"   Could not inspect port {port}: {exc}")
        return

    pids = sorted({int(pid) for pid in result.stdout.split() if pid.isdigit()})
    if not pids:
        return

    print(f"   Stopping {len(pids)} process(es) on port {port}: {', '.join(map(str, pids))}")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            print(f"   No permission to stop process {pid}")

    deadline = time.time() + 3
    remaining = set(pids)
    while remaining and time.time() < deadline:
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remaining.remove(pid)
        if remaining:
            time.sleep(0.1)

    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"   Force-stopped process {pid} after graceful timeout.")
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"   No permission to force-stop process {pid}")

def get_network_ip():
    """Get the local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Unknown"

def main():
    # Configuration
    root_dir = Path(__file__).resolve().parent.parent
    frontend_dir = root_dir / "frontend"
    is_dev = "--dev" in sys.argv or os.environ.get("H2L_MODE") == "dev"
    is_public = "--public" in sys.argv or os.environ.get("H2L_PUBLIC") == "true"
    host = "0.0.0.0" if is_public else os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))

    print("\n🚀 H2L Thesis System Startup")
    print("=============================")
    
    # Try to cleanup the configured port to prevent 'Address already in use'.
    print(f"🧹 Ensuring port {port} is free...")
    kill_port(port)
    if is_dev:
        kill_port(5173)

    # Environment Overrides for Full Performance
    # H2L_SAFE_START respects existing env var; defaults to false for full performance
    if "H2L_SAFE_START" not in os.environ:
        os.environ["H2L_SAFE_START"] = "false"
    os.environ["ENABLE_DENSE_RUNTIME"] = "true"
    os.environ["USE_RERANK"] = "true"

    processes = []

    try:
        # Start Frontend Dev Server if requested
        if is_dev:
            print("🌐 Starting Frontend Dev Server (Port 5173)...")
            frontend_args = ["npm", "run", "dev"]
            if is_public:
                frontend_args.extend(["--", "--host"])
            frontend_proc = subprocess.Popen(
                frontend_args,
                cwd=frontend_dir,
                stdout=None,
                stderr=None
            )
            processes.append(frontend_proc)
            time.sleep(2)

        # Print Links & Security Notice
        local_ip = "127.0.0.1"
        network_ip = get_network_ip() if is_public else None
        
        print("\n✅ Access Links:")
        print(f"   ➜  Local:   http://{local_ip}:{port}/")
        if network_ip and network_ip != "Unknown":
            print(f"   ➜  Network: http://{network_ip}:{port}/")
            print("   ⚠️  SECURITY NOTICE: Public network access is enabled. Do not expose confidential case data on untrusted networks!")
        else:
            print("   🔒 Localhost Only Mode (Secure for confidential clinical data)")
        
        if is_dev:
            print(f"   ➜  UI Dev:  http://{local_ip}:5173/ (with Hot Reload)")

        print("\n🖥️  Starting Backend Server...")
        print("   Loading models into RAM (this takes 1-2 mins)...")
        
        if is_dev:
            # Run uvicorn in a sub-process
            backend_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.main:app", "--host", host, "--port", str(port), "--reload"],
                cwd=root_dir
            )
            processes.append(backend_proc)
            
            while True:
                time.sleep(1)
                if backend_proc.poll() is not None or (is_dev and frontend_proc.poll() is not None):
                    break
        else:
            # Production mode
            uvicorn.run("api.main:app", host=host, port=port, reload=False, log_level="info")

    except KeyboardInterrupt:
        print("\n\n👋 Stopping all services...")
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        print("✨ Done.")

if __name__ == "__main__":
    main()
