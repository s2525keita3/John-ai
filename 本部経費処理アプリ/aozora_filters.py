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
        # 桜木町：スタッフへの大口振込は支給控除（人件費）側で把握する前提で除外
        | s.str.contains("ヤマグチ", regex=False)
        | s.str.contains("ミカミ", regex=False)
        | s.str.contains("マツ", regex=False)
        | s.str.contains("ナカ", regex=False)
        | s.str.contains("トクラ", regex=False)
        | s.str.contains("タナカ", regex=False)
        | s.str.contains("タカハシ", regex=False)
        | s.str.contains("スズキ", regex=False)
        | s.str.contains("ササキ", regex=False)
        | s.str.contains("オオツジ", regex=False)
        | s.str.contains("イシダミユキ", regex=False)
        | s.str.contains("イシイ", regex=False)
        | s.str.contains("サトウ", regex=False)
        | st.str.startswith("PE ")
        | s.str.contains("ｼﾔｶｲﾎｹﾝﾘﾖｳ", regex=False)
        | s.str.contains("社会保険", regex=False)
        # 医療保険（国保連合会・支払基金など）：支給控除側で把握する前提で除外
        | s.str.contains("医療保険", regex=False)
        | s.str.contains("国保連合会", regex=False)
        | s.str.contains("診療報酬支払基金", regex=False)
        # 小口補充（ATM出金）は小口入力側で明細化するため除外
        | (s.str.contains("ATM", regex=False) & s.str.contains("ゆうちょ", regex=False))
    )

    return df[~drop].copy()
