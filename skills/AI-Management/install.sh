#!/usr/bin/env python3
"""AI Management — Install, Build & Sync"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_management.cli import main

if __name__ == "__main__":
    sys.exit(main())
