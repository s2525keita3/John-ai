"""
横浜信用金庫 入出金明細を Excel（.xlsx）から読み込む。

想定レイアウト（「横浜信金◯月.xlsx」ベース）:
- 先頭に表題行があってもよい
- どこかの行に「日付」「入金」「出金」が並ぶ列見出し
- 日付の無い行（残高のみ等）は除外
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime

import pandas as pd


def _norm_header(s: object) -> str:
    t = str(s).strip().replace("\u3000", " ")
    return re.sub(r"\s+", "", t)


def _find_header_row(raw: pd.DataFrame, max_scan: int = 25) -> int:
    n = min(max_scan, len(raw))
    for i in range(n):
        cells = [_norm_header(c) for c in raw.iloc[i].tolist()]
        joined = "".join(cells)
        if "日付" in joined and "入金" in joined and "出金" in joined:
            return i
    raise ValueError(
        "Excel のヘッダー行が見つかりません。"
        "1行に「日付」「入金」「出金」の列見出しがある形式にしてください。"
    )


def _format_date_cell(v: object) -> str:
    if pd.isna(v):
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return s[:32]


def _first_col(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for c in df.columns:
        cn = _norm_header(c)
        if cn in names:
            return str(c)
    for c in df.columns:
        cn = _norm_header(c)
        for n in names:
            if n in cn and len(cn) <= 12:
                return str(c)
    return None


def read_yokohama_bank_excel(file_bytes: bytes, *, sheet_name: int | str = 0) -> pd.DataFrame:
    """
    横浜信金入出金明細の xlsx を、CSV プリセットと同じ列名の DataFrame にする。
    """
    buf = io.BytesIO(file_bytes)
    peek = pd.read_excel(buf, sheet_name=sheet_name, header=None, dtype=object, engine="openpyxl")
    header_idx = _find_header_row(peek)
    buf.seek(0)
    df = pd.read_excel(buf, sheet_name=sheet_name, header=header_idx, dtype=object, engine="openpyxl")

    c_date = _first_col(df, ("日付", "取引日"))
    c_kamoku = _first_col(df, ("科目",))
    c_payee = _first_col(df, ("支払先", "相手先"))
    c_sum = _first_col(df, ("摘要", "お取引内容", "内容"))
    c_in = _first_col(df, ("入金", "お預かり"))
    c_out = _first_col(df, ("出金", "お支払"))
    c_bal = _first_col(df, ("計", "残高"))

    if not c_date or not c_in or not c_out:
        raise ValueError(
            "必須列が見つかりません（日付・入金・出金）。"
            f" 列一覧: {[str(c) for c in df.columns]}"
        )

    n = len(df)
    z = pd.Series([""] * n, index=df.index, dtype=object)
    out = pd.DataFrame(
        {
            "日付": df[c_date].map(_format_date_cell),
            "科目": df[c_kamoku].fillna("").astype(str).str.strip() if c_kamoku else z,
            "支払先": df[c_payee].fillna("").astype(str).str.strip() if c_payee else z,
            "摘要": df[c_sum].fillna("").astype(str).str.strip() if c_sum else z,
            "入金": pd.to_numeric(df[c_in], errors="coerce").fillna(0),
            "出金": pd.to_numeric(df[c_out], errors="coerce").fillna(0),
            "計": pd.to_numeric(df[c_bal], errors="coerce").fillna(0) if c_bal else pd.Series([0.0] * n, index=df.index),
        }
    )

    out = out[out["日付"].astype(str).str.strip().ne("")].copy()
    return out.reset_index(drop=True)
