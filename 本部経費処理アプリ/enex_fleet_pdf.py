"""
エネオス法人ガソリンカード（エネクスフリート株式会社）請求書PDFから、
本部対象カード（既定: 0001〜0004）について **（車番　計）** 行の金額のみを抽出する。

給油明細の1件ごとの金額は使わず、請求書上のカード別「車番計」合計のみを参照する。
テキスト抽出は PyMuPDF（fitz）。
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

try:
    import fitz  # PyMuPDF
except ImportError as e:  # pragma: no cover
    fitz = None  # type: ignore
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None

# 本部（ジョン様設定）
DEFAULT_HQ_CARDS = frozenset({"0001", "0002", "0003", "0004"})

_YEAR_INVOICE_RE = re.compile(r"(20\d{2})年\s*\d{1,2}月")
_YEAR_IN_FILENAME_RE = re.compile(r"_(\d{4})(\d{2})(\d{2})\.pdf", re.I)
_SHIMEBI_RE = re.compile(r"締日\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_DETAIL_HEAD_RE = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+")
_SHABAN_KEI_RE = re.compile(r"（\s*車番\s*計\s*）")


def _extract_year(full_text: str, filename: str) -> int:
    m = _YEAR_INVOICE_RE.search(full_text)
    if m:
        return int(m.group(1))
    m = _YEAR_IN_FILENAME_RE.search(filename or "")
    if m:
        return int(m.group(1))
    return date.today().year


def _extract_invoice_date_str(full_text: str, filename: str, year: int) -> str:
    """請求締日（なければファイル名の日付、なければ当年12/31）。"""
    m = _SHIMEBI_RE.search(full_text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    m = _YEAR_IN_FILENAME_RE.search(filename or "")
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    return f"{year}-12-31"


def _is_shaban_kei_line(line: str) -> bool:
    """（車番　計）の合計行。注釈・参考行は除外。"""
    if "※" in line or "参考" in line:
        return False
    return _SHABAN_KEI_RE.search(line) is not None


def _amount_from_shaban_kei_line(line: str) -> float | None:
    if not _is_shaban_kei_line(line):
        return None
    nums = re.findall(r"\d+", line)
    if not nums:
        return None
    return float(int(nums[-1]))


def parse_enex_fleet_pdf_bytes(
    raw: bytes,
    *,
    filename: str = "",
    hq_cards: frozenset[str] | None = None,
) -> pd.DataFrame:
    """
    請求書PDFから本部カードごとの **（車番　計）** 行の金額のみを1行ずつ抽出する。

    明細行の合計ではなく、PDF上「車番　計」の横に出る **カード単位の合計金額** を参照する。
    直前に現れた本部カード（0001〜0004）の明細ブロックに紐づける。他カード（0101等）の明細が
    挟まったあとは紐づけをリセットする。
    """
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF (pymupdf) が未インストールです。`pip install pymupdf` を実行してください。"
        ) from _IMPORT_ERR

    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        full_text = "".join(p.get_text() for p in doc)
    finally:
        doc.close()

    year = _extract_year(full_text, filename)
    date_str = _extract_invoice_date_str(full_text, filename, year)
    cards = hq_cards if hq_cards is not None else DEFAULT_HQ_CARDS
    rows: list[dict] = []
    last_hq_card: str | None = None

    for line in full_text.splitlines():
        dm = _DETAIL_HEAD_RE.match(line)
        if dm:
            card = dm.group(1)
            last_hq_card = card if card in cards else None
            continue

        amt = _amount_from_shaban_kei_line(line)
        if amt is None or last_hq_card is None:
            continue

        card = last_hq_card
        summary = f"エネフリ {card} 車番計（請求書・カード合計）"
        rows.append(
            {
                "日付": date_str,
                "摘要": summary,
                "出金額": amt,
                "入金額": 0.0,
                "カード番号": card,
            }
        )
        last_hq_card = None

    return pd.DataFrame(rows)


def filter_exclude_orico(df: pd.DataFrame, summary_col: str = "摘要") -> pd.DataFrame:
    """摘要に「オリコ」または半角カナ「ｵﾘｺ」を含む行を除外（ガソリンはエネフリPDF等で集計）。"""
    if summary_col not in df.columns:
        return df
    s = df[summary_col].fillna("").astype(str)
    mask = s.str.contains("オリコ", regex=False) | s.str.contains("ｵﾘｺ", regex=False)
    return df[~mask].copy()


def filter_amex_hq_noise(
    df: pd.DataFrame,
    summary_col: str = "摘要",
    out_col: str = "出金額",
) -> pd.DataFrame:
    """
    アメックス本部振分向けの除外:
    - 前回分口座振替金額（締め替え・振分対象外）
    - ソフトバンクＭ の一括請求（全社合計・各店按分済みのため約17〜20万円帯を除外）
    """
    from classifier import parse_amount_cell

    if summary_col not in df.columns:
        return df
    s = df[summary_col].fillna("").astype(str)
    drop = s.str.contains("前回分口座振替金額", regex=False)

    amt = None
    if out_col in df.columns:
        amt = df[out_col].map(parse_amount_cell).fillna(0).abs()
    if amt is not None:
        sb = s.str.contains("ソフトバンク", regex=False) & (
            s.str.contains("Ｍ", regex=False) | s.str.contains("M", regex=False)
        )
        bulk = (amt >= 170_000) & (amt <= 210_000)
        drop = drop | (sb & bulk)

    return df[~drop].copy()
