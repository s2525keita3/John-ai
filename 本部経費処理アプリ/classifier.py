"""
本部経費の取引を自社PL勘定項目へ振り分け（要件定義書 v2 のステップ3〜4 の簡易版）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Classification = Literal["確定", "要確認", "判断不能"]


@dataclass
class MasterRow:
    keyword: str
    pl_account: str
    amount_min: float | None
    amount_max: float | None
    source: str  # あおぞら・アメックス・横浜信金・小口現金・定例


def load_master_dataframe(df: pd.DataFrame) -> list[MasterRow]:
    """UIの data_editor から生成した DataFrame をマスタ行に変換。"""
    rows: list[MasterRow] = []
    for _, r in df.iterrows():
        kw = str(r.get("摘要キーワード", "") or "").strip()
        pl = str(r.get("自社PL勘定項目", "") or "").strip()
        if pl in ("", "（未選択）", "—"):
            pl = ""
        if not kw or not pl:
            continue
        lo = r.get("金額下限")
        hi = r.get("金額上限")
        rows.append(
            MasterRow(
                keyword=kw,
                pl_account=pl,
                amount_min=float(lo) if pd.notna(lo) and str(lo).strip() != "" else None,
                amount_max=float(hi) if pd.notna(hi) and str(hi).strip() != "" else None,
                source=str(r.get("データソース区分", "") or "").strip(),
            )
        )
    return rows


def load_master_csv(path_or_buffer) -> list[MasterRow]:
    df = pd.read_csv(path_or_buffer, encoding="utf-8-sig")
    return load_master_dataframe(df)


def parse_amount_cell(v) -> float | None:
    """CSVの金額セル（カンマ区切り文字列・数値）を float に。"""
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s == "" or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _expense_amount(row: pd.Series) -> float:
    """出金を正の数として扱う。列名は統一フォーマット想定。"""
    for col in ("出金額", "支出額"):
        if col in row.index:
            v = parse_amount_cell(row[col])
            if v is not None and v != 0:
                return abs(v)
    if "金額" in row.index:
        v = parse_amount_cell(row.get("金額"))
        if v is not None:
            if v < 0:
                return 0.0
            if v != 0:
                return abs(v)
    if "入金額" in row.index:
        v = parse_amount_cell(row.get("入金額"))
        if v is not None and v < 0:
            return abs(v)
    return 0.0


def classify_row(
    summary: str,
    amount: float,
    master: list[MasterRow],
    source_filter: str | None = None,
) -> tuple[Classification, str | None, MasterRow | None]:
    """
    最初にマッチしたルールで判定（複数マッチ時は表の上から優先）。
    返り値: (分類, PL項目名, マッチしたマスタ行)
    """
    summary_norm = summary.strip()
    candidates: list[MasterRow] = []
    for m in master:
        if source_filter and m.source and m.source != source_filter:
            continue
        if m.keyword in summary_norm:
            candidates.append(m)

    if not candidates:
        return "判断不能", None, None

    # 長いキーワードを優先（「アマゾン」より「アマゾンサービシーズインターナショナル」）
    candidates.sort(key=lambda m: len(m.keyword), reverse=True)

    def _in_range(m: MasterRow) -> bool:
        lo = m.amount_min if m.amount_min is not None else float("-inf")
        hi = m.amount_max if m.amount_max is not None else float("inf")
        return lo <= amount <= hi

    # 金額レンジが合う候補を優先（ソフトバンク6,800円帯と1万円帯の分離など）
    ranged = [m for m in candidates if m.amount_min is not None or m.amount_max is not None]
    for m in ranged:
        if _in_range(m):
            return "確定", m.pl_account, m
    # レンジなしの候補
    unbounded = [m for m in candidates if m.amount_min is None and m.amount_max is None]
    if unbounded:
        return "確定", unbounded[0].pl_account, unbounded[0]

    m0 = candidates[0]
    lo = m0.amount_min if m0.amount_min is not None else float("-inf")
    hi = m0.amount_max if m0.amount_max is not None else float("inf")
    if lo <= amount <= hi:
        return "確定", m0.pl_account, m0
    return "要確認", m0.pl_account, m0


def classify_dataframe(
    df: pd.DataFrame,
    master: list[MasterRow],
    summary_col: str = "摘要",
    source_col: str | None = "データソース区分",
) -> pd.DataFrame:
    out = df.copy()
    classes: list[str] = []
    pls: list[str | None] = []
    notes: list[str] = []

    for _, row in out.iterrows():
        sm = str(row.get(summary_col, "") or "")
        amt = _expense_amount(row)
        src = None
        if source_col and source_col in row.index:
            v = row.get(source_col)
            src = str(v).strip() if pd.notna(v) and str(v).strip() else None

        c, pl, _ = classify_row(sm, amt, master, source_filter=src)
        classes.append(c)
        pls.append(pl if pl else "")
        if c == "要確認":
            notes.append("キーワード一致だが金額が想定レンジ外")
        elif c == "判断不能":
            notes.append("マスタに一致する摘要キーワードなし")
        else:
            notes.append("")

    out["分類結果"] = classes
    out["振分PL項目"] = pls
    out["メモ"] = notes
    return out


def aggregate_by_pl(df: pd.DataFrame) -> pd.DataFrame:
    """確定・要確認も含め、振分PL項目ごとに出金・入金合計（簡易）。取込対象外は集計から除く。"""
    if "振分PL項目" not in df.columns:
        return pd.DataFrame()
    has_out = "出金額" in df.columns
    has_in = "入金額" in df.columns
    if not has_out and not has_in:
        return pd.DataFrame()
    tmp = df.copy()
    if "取込対象外" in tmp.columns:
        tmp = tmp[~tmp["取込対象外"].fillna(False)]
    if has_out:
        tmp["_出金"] = pd.to_numeric(tmp["出金額"], errors="coerce").fillna(0).abs()
    else:
        tmp["_出金"] = 0.0
    if has_in:
        tmp["_入金"] = pd.to_numeric(tmp["入金額"], errors="coerce").fillna(0).abs()
    else:
        tmp["_入金"] = 0.0
    g = (
        tmp.groupby("振分PL項目", dropna=False)
        .agg({"_出金": "sum", "_入金": "sum"})
        .reset_index()
    )
    g.columns = ["自社PL勘定項目", "合計額（出金）", "合計額（入金）"]
    g["_sort"] = g["合計額（出金）"] + g["合計額（入金）"]
    return g.sort_values("_sort", ascending=False).drop(columns=["_sort"])
