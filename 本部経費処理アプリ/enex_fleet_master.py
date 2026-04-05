"""
エネクスフリート請求PDFの抽出行に、カードマスタ（拠点・車両・スタッフ）を紐づける。

PDF側の「カード番号」は4桁（例: 0001, 0101）。マスタの番号は数字ならゼロ埋め4桁に正規化する。
"""
from __future__ import annotations

import pandas as pd


def normalize_enex_card_id(value: object) -> str:
    """マスタ・抽出の双方で使う4桁カードID。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    if len(digits) <= 4:
        return digits.zfill(4)
    return digits[-4:]


def prepare_enex_card_master_df(df: pd.DataFrame) -> pd.DataFrame:
    """結合用に列をそろえる。必須: カード番号・拠点・スタッフ名（車両番号は任意）。"""
    if "カード番号" not in df.columns:
        raise ValueError("カードマスタに「カード番号」列が必要です。")
    out = df.copy()
    out["カード番号"] = out["カード番号"].map(normalize_enex_card_id)
    if "拠点" not in out.columns:
        out["拠点"] = ""
    else:
        out["拠点"] = out["拠点"].fillna("").astype(str)
    if "スタッフ名" not in out.columns:
        out["スタッフ名"] = ""
    else:
        out["スタッフ名"] = out["スタッフ名"].fillna("").astype(str)
    if "車両番号" not in out.columns:
        out["車両番号"] = ""
    else:
        out["車両番号"] = out["車両番号"].fillna("").astype(str)
    # 同一カードが重複した場合は先頭行を採用
    out = out.drop_duplicates(subset=["カード番号"], keep="first")
    return out[["カード番号", "拠点", "車両番号", "スタッフ名"]]


def merge_enex_extract_with_master(work: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """抽出1行＝カード別車番計に、拠点・車両・スタッフを付与。"""
    if work.empty or "カード番号" not in work.columns:
        return work
    m = prepare_enex_card_master_df(master)
    out = work.merge(m, on="カード番号", how="left", suffixes=("", "_m"))
    for col in ("拠点", "車両番号", "スタッフ名"):
        if col not in out.columns:
            continue
        na = out[col].isna()
        out[col] = out[col].fillna("").astype(str)
        out.loc[na, col] = "（マスタ未登録）"
    return out


def summarize_enex_by_base(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "拠点" not in df.columns or "出金額" not in df.columns:
        return pd.DataFrame()
    g = df.groupby("拠点", dropna=False)["出金額"].sum().reset_index()
    g.columns = ["拠点", "合計（出金）"]
    return g.sort_values("合計（出金）", ascending=False)


def summarize_enex_by_staff(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "スタッフ名" not in df.columns or "出金額" not in df.columns:
        return pd.DataFrame()
    keys = [k for k in ("拠点", "スタッフ名") if k in df.columns]
    if not keys:
        return pd.DataFrame()
    g = df.groupby(keys, dropna=False)["出金額"].sum().reset_index()
    g = g.rename(columns={"出金額": "合計（出金）"})
    return g.sort_values("合計（出金）", ascending=False)
