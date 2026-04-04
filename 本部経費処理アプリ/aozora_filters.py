"""
あおぞらネット銀行（法人口座）CSV向けの振分除外（本部運用ルール）。
"""
from __future__ import annotations

import pandas as pd


def filter_aozora_hq_noise(df: pd.DataFrame, summary_col: str = "摘要") -> pd.DataFrame:
    """
    資金移動・支給控除と二重になる支出・エネフリで別途見る決済などを除外。

    - 振替 カ）ジヨン…（口座間の資金移動）
    - 振込 ヨコハマシンキン カ）ジヨン（資金移動）
    - 三菱UFJ・シブヤケイタ（役員報酬／人件費は支給控除で把握）
    - ラクテン イシダユミエ（支給控除）
    - PE 地方税・税務署（電子納付）
    - 社会保険料（半角ｼﾔｶｲﾎｹﾝﾘﾖｳ等／支給控除）

    オリコ（全角・半角ｵﾘｺ）は filter_exclude_orico で除外。
    """
    if summary_col not in df.columns:
        return df
    s = df[summary_col].fillna("").astype(str)
    st = s.str.strip()

    drop = (
        (s.str.contains("振替", regex=False) & s.str.contains("カ）ジヨン", regex=False))
        | (s.str.contains("ヨコハマシンキン", regex=False) & s.str.contains("カ）ジヨン", regex=False))
        | s.str.contains("ミツビシユ－エフジエイ シブヤケイタ", regex=False)
        | s.str.contains("イシダユミエ", regex=False)
        | st.str.startswith("PE ")
        | s.str.contains("ｼﾔｶｲﾎｹﾝﾘﾖｳ", regex=False)
        | s.str.contains("社会保険", regex=False)
    )

    return df[~drop].copy()
