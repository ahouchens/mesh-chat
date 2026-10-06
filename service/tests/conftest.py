from __future__ import annotations

import sys
from pathlib import Path

SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"
SERVICE_ROOT = SERVICE_SRC.parent
sys.path.insert(0, str(SERVICE_SRC))
sys.path.insert(0, str(SERVICE_ROOT))
