from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "logfire-plugin")

PROJECT_ROOT = Path(__file__).resolve().parent
TESTS_DIR = PROJECT_ROOT / "tests"
SRC_ROOT = PROJECT_ROOT / "src"

for candidate in (str(PROJECT_ROOT), str(TESTS_DIR), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
