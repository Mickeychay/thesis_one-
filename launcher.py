import os
import sys
import subprocess
from pathlib import Path

def main():
    root_dir = Path(__file__).parent.absolute()

    print("\n🚀 H2L Thesis Launcher (delegating to start.py --dev)")
    print("=====================================================")

    # Keep launcher as a convenience entrypoint, but let start.py own process
    # lifecycle, port cleanup, and frontend/backend orchestration.
    os.environ.setdefault("H2L_SAFE_START", "false")
    os.environ.setdefault("ENABLE_DENSE_RUNTIME", "true")
    os.environ.setdefault("USE_RERANK", "true")
    os.environ["PYTHONPATH"] = str(root_dir)

    raise SystemExit(subprocess.call([sys.executable, "start.py", "--dev"], cwd=root_dir))

if __name__ == "__main__":
    main()
