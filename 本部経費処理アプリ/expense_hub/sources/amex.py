"""
入力ソース1：アメックスのご利用明細CSV（会員サイトの「activity.csv」）。
列＝ご利用日, データ処理日, ご利用内容, 金額, 海外通貨利用金額, 換算レート（CP932 / UTF-8）。
マイナス行は「前回分口座振替金額」＝支払い済みの返済なので経費にしない。
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime

from ..models import ExpenseRecord, PlMatch, Status
from ..vendor import normalize_vendor

HEADER = ["ご利用日", "データ処理日", "ご利用内容", "金額"]
EXCLUDE_WORDS = ("口座振替", "お支払", "返済", "入金")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("アメックスCSVの文字コードを判定できません（UTF-8／CP932以外）")


def _date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _amount(s: str) -> int:
    return int(round(float((s or "0").replace(",", "").replace("¥", "").replace("円", "").strip() or 0)))


class AmexCsvSource:
    source_type = "amex_csv"
    label = "アメックス CSV"

    def can_parse(self, raw: bytes, filename: str = "") -> bool:
        try:
            first = _decode(raw).splitlines()[0]
        except (ValueError, IndexError):
            return False
        return all(h in first for h in HEADER)

    def parse(self, raw: bytes, filename: str, file_hash: str) -> list[ExpenseRecord]:
        text = _decode(raw)
        rows = list(csv.reader(io.StringIO(text)))
        head = rows[0]
        idx = {h: head.index(h) for h in head}
        out: list[ExpenseRecord] = []
        for n, r in enumerate(rows[1:], start=2):  # CSVの行番号（ヘッダー=1行目）
            if not any(c.strip() for c in r):
                continue
            vendor = r[idx["ご利用内容"]].strip()
            amt = _amount(r[idx["金額"]])
            rec = ExpenseRecord(
                id=hashlib.sha1(f"{file_hash}:{n}".encode()).hexdigest()[:12],
                source_type=self.source_type,
                source_file_id=filename,
                source_file_hash=file_hash,
                source_row_number=n,
                transaction_date=_date(r[idx["ご利用日"]]),
                processing_date=_date(r[idx["データ処理日"]]),
                vendor_raw=vendor,
                vendor_normalized=normalize_vendor(vendor),
                amount=amt,
                foreign_amount=r[idx["海外通貨利用金額"]].strip() if "海外通貨利用金額" in idx else "",
            )
            rec.log("IMPORTED", f"{filename} 行{n}")
            if amt < 0 or any(w in vendor for w in EXCLUDE_WORDS):
                rec.approval_status = Status.EXCLUDED
                rec.expense_category = "対象外"
                rec.pl_note_match_status = PlMatch.NOT_APPLICABLE
                rec.judgement_reason = "口座振替・返済行（カード代金の支払い）＝経費ではない"
            else:
                rec.approval_status = Status.NORMALIZED
            rec.log(rec.approval_status.value, rec.judgement_reason)
            out.append(rec)
        return out
