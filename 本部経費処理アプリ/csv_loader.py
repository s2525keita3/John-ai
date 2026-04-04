"""
銀行・カード明細CSVのエンコーディング自動判定
"""
from __future__ import annotations

import io

import pandas as pd


def read_csv_auto(file_bytes: bytes) -> pd.DataFrame:
    """utf-8-sig → cp932 → utf-8 の順で試す（あおぞらは cp932 が多い）"""
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise last_err or UnicodeDecodeError("read", b"", 0, 0, "unknown encoding")
