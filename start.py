#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L Root Startup Script
Delegates to api.start for local development and production runtime.
"""
import sys
from pathlib import Path

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from api.start import main

if __name__ == "__main__":
    main()
