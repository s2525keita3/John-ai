"""
一画面フローの裏側：原本取込 → 自動整形 → 重複検出 → PLセルメモ照合 → 集計・CSV出力。
画面（Streamlit）からはこの関数だけを呼ぶ。
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .ledger import Ledger
from .departments import STORES, plan_actual_month_map
from .matcher import match, match_allocations
from .models import ExpenseRecord, PlMatch, PlNoteLine, Status
from .pl_notes import DEFAULT_SHEET, cell_note_totals, read_note_lines
from .pl_source import Grid, grids_from_xlsx
from .sources import detect_source, file_hash


@dataclass
class RunResult:
    records: list[ExpenseRecord]
    unmatched_notes: list[PlNoteLine]
    cell_totals: list[dict]
    source_file_hash: str
    duplicate_of: dict | None = None
    grid: Grid | None = None
    summary: dict = field(default_factory=dict)


def run(
    src_bytes: bytes,
    src_name: str,
    pl: dict[str, Grid] | bytes,
    target_month: str,
    sheet: str = DEFAULT_SHEET,
    ledger: Ledger | None = None,
) -> RunResult:
    """pl＝タブ名→Grid（スプシ直結）か、収支計画のxlsxバイト列。店舗タブがあれば按分も照合する。"""
    src = detect_source(src_bytes, src_name)
    if src is None:
        raise ValueError(f"{src_name}：対応している入力ソースの形式ではありません")
    h = file_hash(src_bytes)
    dup = ledger.already_imported(h) if ledger else None

    records = src.parse(src_bytes, src_name, h)
    grids = pl if isinstance(pl, dict) else grids_from_xlsx(pl, pl_sheets(sheet))
    if sheet not in grids:
        raise ValueError(f"PLにタブ「{sheet}」がありません")
    grid = grids[sheet]
    notes = read_note_lines(grid)
    unmatched = match(records, notes, target_month)
    store_notes = {
        d.name: read_note_lines(grids[d.sheet], month_map=plan_actual_month_map()) for d in STORES if d.sheet in grids
    }
    match_allocations(records, store_notes, target_month)
    totals = cell_note_totals(grid, target_month)

    res = RunResult(records, unmatched, totals, h, dup, grid)
    res.summary = summarize(records)
    if ledger and not dup:
        ledger.save_import(src.source_type, src_name, h, target_month, records)
    return res


def pl_sheets(sheet: str = DEFAULT_SHEET) -> list[str]:
    """照合に読むタブ：本部（または指定タブ）＋店舗収支タブ。"""
    return [sheet] + [d.sheet for d in STORES]


def summarize(records: list[ExpenseRecord]) -> dict:
    exp = [r for r in records if r.approval_status != Status.EXCLUDED]
    exc = [r for r in records if r.approval_status == Status.EXCLUDED]
    diff = [r for r in exp if r.pl_note_match_status == PlMatch.AMOUNT_DIFF]
    return {
        "行数": len(records),
        "経費総額": sum(r.amount for r in exp),
        "経費件数": len(exp),
        "除外額（口座振替等）": sum(r.amount for r in exc),
        "按分一致": sum(1 for r in exp if r.pl_note_match_status == PlMatch.ALLOCATED),
        "自動確認済み": sum(1 for r in exp if r.approval_status == Status.AUTO_MATCHED),
        "要確認": sum(1 for r in exp if r.approval_status == Status.REVIEW_REQUIRED),
        "差異額": sum(r.amount - (r.pl_amount or 0) for r in diff),
        "PL未反映": sum(1 for r in exp if r.pl_note_match_status == PlMatch.NOT_IN_PL),
        "計上月差": sum(1 for r in exp if r.pl_note_match_status == PlMatch.MONTH_DIFF),
    }


EXPORT_COLS = [
    ("source_row_number", "原本行"),
    ("transaction_date", "利用日"),
    ("processing_date", "処理日"),
    ("vendor_raw", "利用先"),
    ("amount", "金額"),
    ("source_type", "入力元"),
    ("expense_category", "科目"),
    ("department", "部門"),
    ("pl_cell", "PLセル"),
    ("pl_amount", "PLメモ金額"),
    ("pl_note_match_status", "PL照合"),
    ("allocation_lines", "按分"),
    ("judgement_reason", "判定理由"),
    ("approval_status", "ステータス"),
    ("reviewer", "確認者"),
]


def allocation_text(r: ExpenseRecord) -> str:
    return "／".join(f"{a['department']} {a['cell']} {a['amount']:,}" for a in r.allocation_lines)


def to_csv(records: list[ExpenseRecord]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([j for _, j in EXPORT_COLS])
    for r in sorted(records, key=lambda x: (x.transaction_date or 0, x.source_row_number)):
        d = r.to_row()
        d["allocation_lines"] = allocation_text(r)
        w.writerow(["" if d[k] is None else d[k] for k, _ in EXPORT_COLS])
    return buf.getvalue().encode("utf-8-sig")  # Excelで文字化けしないようBOM付き
