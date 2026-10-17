"""Public Streamlit entrypoint: session-only annotations, no API calls."""
from __future__ import annotations

import os
import runpy
from pathlib import Path

os.environ["POLYGLOT_PUBLIC_DEMO"] = "1"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
