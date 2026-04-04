"""
Streamlit Cloud 用エントリ（パスは ASCII のみ）。
訪問件数仕分けアプリをデプロイするときは Main file path にこれを指定。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_APP_DIR = _ROOT / "訪問件数仕分けアプリ"

sys.path.insert(0, str(_APP_DIR))

_p = _APP_DIR / "app.py"
spec = importlib.util.spec_from_file_location("_homon_streamlit_app", _p)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {_p}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
