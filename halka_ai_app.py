"""
Streamlit Cloud 用エントリ（パスは ASCII のみ）。
Main file path にこのファイルを指定し、halka_ai/app.py を読み込む。

ローカル: リポジトリルートで
  streamlit run halka_ai_app.py
  または
  streamlit run halka_ai/app.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "halka_ai"))

_p = _ROOT / "halka_ai" / "app.py"
spec = importlib.util.spec_from_file_location("_halka_streamlit_app", _p)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {_p}")
mod = importlib.util.module_from_spec(spec)
# exec 前に登録（dataclass / Py3.14 で cls.__module__ が解決できるように）
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
