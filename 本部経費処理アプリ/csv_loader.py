"""
銀行・カード明細CSVのエンコーディング自動判定
"""
from __future__ import annotations

import io

import pandas as pd


def is_probably_pdf_bytes(raw: bytes) -> bool:
    """先頭が PDF マジックナンバーか（取引PDFをCSV欄に載せた誤りの検出用）。"""
    return len(raw) >= 4 and raw[:4] == b"%PDF"


def read_csv_auto(file_bytes: bytes) -> pd.DataFrame:
    """
    複数エンコーディングを試す（日本語CSVは cp932 / UTF-8 / UTF-16 など混在しがち）。
    最後に latin-1 で読む（常にデコード可能・文字化けの可能性あり）。
    """
    encodings = (
        "utf-8-sig",
        "utf-8",
        "cp932",
        "euc-jp",
        "iso2022_jp",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
    )
    last_err: Exception | None = None
    bio = io.BytesIO(file_bytes)
    for enc in encodings:
        try:
            bio.seek(0)
            return pd.read_csv(bio, encoding=enc)
        except (UnicodeDecodeError, UnicodeError) as e:
            last_err = e
            continue
    try:
        bio.seek(0)
        return pd.read_csv(bio, encoding="latin-1")
    except Exception:
        raise last_err or UnicodeDecodeError("read", b"", 0, 0, "unknown encoding")
