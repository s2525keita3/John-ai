"""
明細向けの軽量フィルタ（本部経費処理アプリ・enex_fleet_pdf から独立）。
"""
from __future__ import annotations

import pandas as pd


def filter_exclude_orico(
    df: pd.DataFrame,
    *,
    summary_col: str = "摘要",
) -> pd.DataFrame:
    """摘要に「オリコ」または半角カナ「ｵﾘｺ」を含む行を除外。"""
    if summary_col not in df.columns:
        return df
    s = df[summary_col].fillna("").astype(str)
    mask = s.str.contains("オリコ", regex=False) | s.str.contains("ｵﾘｺ", regex=False)
    return df[~mask].copy()
