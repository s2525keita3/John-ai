"""
原本明細 × PLセルメモ の照合（要件定義 §8・§9・§11）。

段階的に当てる。1本のメモ明細は1本の原本にしか使わない。
  1. 利用先＋日付＋金額が一致           → 一致（自動確認済み）
  2. 日付＋金額は一致・利用先名が違う    → 要確認（候補を提示）
  3. 利用先＋日付は一致・金額が違う      → 金額差異（要確認）
  4. 利用先＋金額は一致・別の月列に計上  → 計上月差（要確認）
  5. どれにも当たらない                  → PL未反映候補（要確認）
  6. 金額差異のうち、差額が店舗タブに按分されていれば → 按分一致（match_allocations）
差異があるものは自動で確定しない。PLへの書き込みもしない。
"""
from __future__ import annotations

from datetime import timedelta
from itertools import product

from .models import ExpenseRecord, PlMatch, PlNoteLine, Status
from .vendor import alias_words, mentions, vendor_similarity

VENDOR_OK = 0.7
DATE_TOL = timedelta(days=3)


def _date_ok(rec: ExpenseRecord, note: PlNoteLine) -> bool:
    if note.date is None or rec.transaction_date is None:
        return False
    return abs(note.date - rec.transaction_date) <= DATE_TOL


def _attach(rec: ExpenseRecord, note: PlNoteLine) -> None:
    rec.pl_sheet = note.sheet
    rec.pl_cell = note.cell
    rec.pl_amount = note.amount
    if not rec.expense_category:
        rec.expense_category = note.row_label or note.category


def match(records: list[ExpenseRecord], notes: list[PlNoteLine], target_month: str) -> list[PlNoteLine]:
    """records を更新し、どの原本にも当たらなかったメモ明細を返す。"""
    used: set[int] = set()
    pending = [r for r in records if r.approval_status != Status.EXCLUDED]
    month_notes = [(i, n) for i, n in enumerate(notes) if n.month_col == target_month]
    other_notes = [(i, n) for i, n in enumerate(notes) if n.month_col != target_month]

    def take(rec, pool, cond):
        best = None
        for i, n in pool:
            if i in used or n.amount is None:
                continue
            ok, score = cond(rec, n)
            if ok and (best is None or score > best[0]):
                best = (score, i, n)
        if best:
            used.add(best[1])
            return best[2]
        return None

    stages = [
        (
            month_notes,
            lambda r, n: (
                n.amount == r.amount and _date_ok(r, n) and vendor_similarity(r.vendor_normalized, n.vendor_normalized) >= VENDOR_OK,
                vendor_similarity(r.vendor_normalized, n.vendor_normalized),
            ),
            PlMatch.MATCHED,
            Status.AUTO_MATCHED,
            lambda r, n: f"PL {n.cell}（{n.row_label}）のメモと利用先・日付・金額が一致",
        ),
        (
            month_notes,
            lambda r, n: (n.amount == r.amount and _date_ok(r, n), 1.0),
            PlMatch.MATCHED,
            Status.REVIEW_REQUIRED,
            lambda r, n: f"PL {n.cell}（{n.row_label}）の「{n.vendor_raw or n.description}」と日付・金額は一致、利用先名が違う＝同一か確認",
        ),
        (
            month_notes,
            lambda r, n: (
                _date_ok(r, n) and vendor_similarity(r.vendor_normalized, n.vendor_normalized) >= VENDOR_OK,
                -abs((n.amount or 0) - r.amount),
            ),
            PlMatch.AMOUNT_DIFF,
            Status.REVIEW_REQUIRED,
            lambda r, n: f"PL {n.cell}（{n.row_label}）のメモは {n.amount:,}円、原本は {r.amount:,}円＝差 {r.amount - n.amount:,}円",
        ),
        (
            other_notes,
            lambda r, n: (
                n.amount == r.amount and vendor_similarity(r.vendor_normalized, n.vendor_normalized) >= VENDOR_OK,
                vendor_similarity(r.vendor_normalized, n.vendor_normalized),
            ),
            PlMatch.MONTH_DIFF,
            Status.REVIEW_REQUIRED,
            lambda r, n: f"{target_month}列ではなく {n.month_col}列の PL {n.cell}（{n.row_label}）に計上済み",
        ),
    ]

    for pool, cond, pl_status, status, reason in stages:
        for rec in pending:
            if rec.pl_note_match_status != PlMatch.UNCHECKED:
                continue
            n = take(rec, pool, cond)
            if n is None:
                continue
            _attach(rec, n)
            rec.pl_note_match_status = pl_status
            rec.approval_status = status
            rec.judgement_reason = reason(rec, n)
            rec.log(status.value, rec.judgement_reason)

    for rec in pending:
        if rec.pl_note_match_status == PlMatch.UNCHECKED:
            rec.pl_note_match_status = PlMatch.NOT_IN_PL
            rec.approval_status = Status.REVIEW_REQUIRED
            rec.judgement_reason = f"PL（{target_month}）のメモに該当なし＝未反映候補"
            rec.log(rec.approval_status.value, rec.judgement_reason)

    return [n for i, n in month_notes if i not in used]


def match_allocations(
    records: list[ExpenseRecord], store_notes: dict[str, list[PlNoteLine]], target_month: str, max_lines: int = 15
) -> None:
    """
    金額差異の行について、差額が同月・同科目の店舗タブのメモに按分されていないかを探す
    （例：Amex の SoftBank 181,593円＝本部 15,614円＋4店舗のスマホ利用料 165,979円）。
    1店舗から最大1明細を選び、合計が差額と1円単位で一致する組合せを探す。
    各明細が同じ請求の呼び名（vendor.ALIASES）で書かれていれば按分一致として自動確認、
    金額しか合わなければ候補として要確認に残す。
    """
    used: set[tuple[str, str, int]] = set()
    for rec in records:
        if rec.pl_note_match_status != PlMatch.AMOUNT_DIFF or rec.pl_amount is None:
            continue
        diff = rec.amount - rec.pl_amount
        if diff <= 0:
            continue
        label = rec.expense_category
        options = []
        for dept, notes in store_notes.items():
            cands = [
                n for n in notes
                if n.month_col == target_month and n.row_label == label and n.amount and n.amount > 0
                and (n.sheet, n.cell, n.line_no) not in used
            ][:max_lines]
            options.append([None] + [(dept, n) for n in cands])
        best = None
        for combo in product(*options):
            picked = [c for c in combo if c]
            if not picked or sum(n.amount for _, n in picked) != diff:
                continue
            words = alias_words(rec.vendor_normalized)
            hits = sum(1 for _, n in picked if words and mentions(n.raw, words))
            score = (hits == len(picked), hits, len(picked))
            if best is None or score > best[0]:
                best = (score, picked)
        if best is None:
            continue
        (all_hit, _, _), picked = best
        rec.allocation_lines = [{"department": "本部", "sheet": rec.pl_sheet, "cell": rec.pl_cell, "amount": rec.pl_amount}] + [
            {"department": d, "sheet": n.sheet, "cell": n.cell, "amount": n.amount} for d, n in picked
        ]
        detail = "＋".join(f"{a['department']} {a['cell']} {a['amount']:,}" for a in rec.allocation_lines)
        if all_hit:
            for _, n in picked:
                used.add((n.sheet, n.cell, n.line_no))
            rec.pl_note_match_status = PlMatch.ALLOCATED
            rec.approval_status = Status.AUTO_MATCHED
            rec.judgement_reason = f"部門按分で一致：{detail}＝{rec.amount:,}円"
        else:
            rec.judgement_reason += f"／按分候補（金額のみ一致・利用先名で裏付けできず）：{detail}"
        rec.log(rec.approval_status.value, rec.judgement_reason)
