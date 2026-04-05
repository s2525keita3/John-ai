"""
エネクスフリート請求PDFの抽出行に、カードマスタ（拠点・車両・スタッフ）を紐づける。

PDF側の「カード番号」は4桁（例: 0001, 0101）。マスタの番号は数字ならゼロ埋め4桁に正規化する。
"""
from __future__ import annotations

import re

import pandas as pd


def staff_name_to_initials_display(name: object) -> str:
    """画面表示用: 姓・名の先頭1文字ずつ（全角スペース区切り想定）。未使用はそのまま。"""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name).strip()
    if not s:
        return ""
    if s == "未使用":
        return "未使用"
    if s.startswith("（") and s.endswith("）"):
        return s
    parts = [p for p in re.split(r"[\s　]+", s) if p]
    if len(parts) >= 2:
        return parts[0][0] + parts[1][0]
    one = parts[0]
    if len(one) <= 1:
        return one
    if len(one) == 2:
        return one[0] + one[1]
    return one[0] + one[-1]


def infer_enex_base_from_card_id(card: str) -> str:
    """
    カード番号（4桁）から拠点を推定。
    運用ルール: 本部 0001〜0004、桜木町 0101〜0114、新子安 0201〜0211、
    白根 0301〜0311、さいわい 0401〜0406（int はゼロ埋め4桁の数値と一致）。
    """
    cid = normalize_enex_card_id(card)
    if not cid:
        return "（拠点要確認）"
    try:
        n = int(cid)
    except ValueError:
        return "（拠点要確認）"
    if 1 <= n <= 4:
        return "本部"
    if 101 <= n <= 114:
        return "桜木町"
    if 201 <= n <= 211:
        return "新子安"
    if 301 <= n <= 311:
        return "白根"
    if 401 <= n <= 406:
        return "さいわい"
    return "（拠点要確認）"


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


def apply_enex_default_card_mapping(work: pd.DataFrame) -> pd.DataFrame:
    """
    PDF抽出直後に必ず付与: 拠点はカード番号から自動推定。
    車両番号・スタッフ名は空（カードマスタCSVで後から上書き可）。
    """
    if work.empty or "カード番号" not in work.columns:
        return work
    out = work.copy()
    out["拠点"] = out["カード番号"].map(
        lambda x: infer_enex_base_from_card_id(normalize_enex_card_id(x))
    )
    out["車両番号"] = ""
    out["スタッフ名"] = ""
    return out


def merge_enex_extract_with_master(work: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """デフォルト推定のうえで、カードマスタCSVの非空セルで上書き（車両・スタッフ・拠点の手修正用）。"""
    if work.empty or "カード番号" not in work.columns:
        return work
    m = prepare_enex_card_master_df(master)
    out = work.merge(m, on="カード番号", how="left", suffixes=("", "_m"))
    for col in ("拠点", "車両番号", "スタッフ名"):
        cm = f"{col}_m"
        if cm not in out.columns:
            continue
        v = out[cm].fillna("").astype(str).str.strip()
        mask = v.ne("")
        out.loc[mask, col] = v[mask]
        out = out.drop(columns=[cm])
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
    tmp = df.copy()
    tmp["スタッフ名"] = tmp["スタッフ名"].map(staff_name_to_initials_display)
    g = tmp.groupby(keys, dropna=False)["出金額"].sum().reset_index()
    g = g.rename(columns={"出金額": "合計（出金）"})
    return g.sort_values("合計（出金）", ascending=False)
