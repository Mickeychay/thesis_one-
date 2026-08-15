import sys
from pathlib import Path

# Ensure root directory is always on sys.path regardless of runner invocation
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
