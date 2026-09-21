"""
入力ソースのアダプタ。1ソース＝1モジュールで、どれも ExpenseRecord のリストを返す。
Phase 2 以降の銀行明細・他カード・領収書・Amazon はここに足す。
"""
from __future__ import annotations

import hashlib

from .amex import AmexCsvSource

SOURCES = {s.source_type: s for s in (AmexCsvSource(),)}


def file_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def detect_source(raw: bytes, filename: str = ""):
    """中身から入力ソースを判定する。判定できなければ None。"""
    for src in SOURCES.values():
        if src.can_parse(raw, filename):
            return src
    return None
