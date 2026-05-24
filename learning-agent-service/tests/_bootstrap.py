from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "logfire-plugin")

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"

for candidate in (str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
