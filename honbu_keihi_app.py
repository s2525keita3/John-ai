"""
Streamlit Cloud 用エントリ（パスは ASCII のみ）。
Main file path にはこのファイルを指定し、
「本部経費処理アプリ/app.py」は日本語フォルダを経由せず読み込む。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_HONBU = _ROOT / "本部経費処理アプリ"

sys.path.insert(0, str(_HONBU))

_p = _HONBU / "app.py"
spec = importlib.util.spec_from_file_location("_honbu_streamlit_app", _p)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {_p}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
