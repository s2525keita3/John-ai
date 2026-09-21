"""
本部経費自動化（親要件定義 v1）の共通データモデル。
入力ソース（Amex・銀行・領収書…）はすべて ExpenseRecord に揃えてから照合する。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum


class Status(str, Enum):
    IMPORTED = "IMPORTED"
    NORMALIZED = "NORMALIZED"
    AUTO_MATCHED = "AUTO_MATCHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    EXCLUDED = "EXCLUDED"
    POSTED_TO_PL = "POSTED_TO_PL"
    CLOSED = "CLOSED"


class PlMatch(str, Enum):
    """PLセルメモとの照合結果。"""
    UNCHECKED = "未照合"
    MATCHED = "一致"
    ALLOCATED = "按分一致"
    AMOUNT_DIFF = "金額差異"
    MONTH_DIFF = "計上月差"
    NOT_IN_PL = "PL未反映"
    NOT_APPLICABLE = "対象外"


@dataclass
class ExpenseRecord:
    id: str
    source_type: str
    source_file_id: str
    source_file_hash: str
    source_row_number: int
    transaction_date: date
    processing_date: date | None
    vendor_raw: str
    vendor_normalized: str
    amount: int
    currency: str = "JPY"
    foreign_amount: str = ""
    expense_category: str = ""
    department: str = ""
    allocation_rule_id: str = ""
    allocation_lines: list[dict] = field(default_factory=list)
    evidence_file_id: str = ""
    pl_sheet: str = ""
    pl_cell: str = ""
    pl_amount: int | None = None
    pl_note_match_status: PlMatch = PlMatch.UNCHECKED
    duplicate_status: str = ""
    approval_status: Status = Status.IMPORTED
    judgement_reason: str = ""
    reviewer: str = ""
    reviewed_at: datetime | None = None
    audit_log: list[dict] = field(default_factory=list)

    def log(self, action: str, detail: str = "", actor: str = "system") -> None:
        self.audit_log.append(
            {"at": datetime.now().isoformat(timespec="seconds"), "actor": actor, "action": action, "detail": detail}
        )

    def to_row(self) -> dict:
        d = asdict(self)
        d["pl_note_match_status"] = self.pl_note_match_status.value
        d["approval_status"] = self.approval_status.value
        return d


@dataclass
class PlNoteLine:
    """PLセルのメモ（Sheetsのノート）を1明細ずつに分解したもの。"""
    sheet: str
    cell: str
    row_label: str
    month_col: str
    line_no: int
    raw: str
    date: date | None
    category: str
    vendor_raw: str
    vendor_normalized: str
    description: str
    amount: int | None
