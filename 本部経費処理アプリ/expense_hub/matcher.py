"""
原本明細 × PLセルメモ の照合（要件定義 §8・§9・§11）。

段階的に当てる。1本のメモ明細は1本の原本にしか使わない。
  探す列＝原本の利用月とその翌月（カード払いは月末付近の利用が翌月列に入る。実データは両方が混在）。
  1. 利用先＋日付＋金額が一致（利用月／翌月の列）→ 一致（自動確認済み）
  2. 日付＋金額は一致・利用先名が違う    → 要確認（候補を提示）
  3. 利用先＋日付は一致・金額が違う      → 金額差異（要確認）
  4. 利用先＋日付＋金額が一致・それ以外の月列に計上 → 計上月差（要確認）※日付も合わせる（定期支払いの別月を拾わない）
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


def _sim(r: ExpenseRecord, n: PlNoteLine) -> float:
    """利用先の近さ。相手先が「代表口座」等の付け替え行は、内容欄の呼び名（ALIASES）でも一致とみなす。"""
    v = vendor_similarity(r.vendor_normalized, n.vendor_normalized)
    words = alias_words(r.vendor_normalized)
    if v < VENDOR_OK and words and mentions(n.description or n.raw, words):
        return 1.0
    return v


def _attach(rec: ExpenseRecord, note: PlNoteLine) -> None:
    rec.pl_sheet = note.sheet
    rec.pl_cell = note.cell
    rec.pl_amount = note.amount
    if not rec.expense_category:
        rec.expense_category = note.row_label or note.category


def _own_months(rec: ExpenseRecord) -> set[str]:
    """この原本が入っていてよい月列＝利用月と翌月。"""
    m = rec.transaction_date.month
    return {f"{m}月", f"{m % 12 + 1}月"}


def match(records: list[ExpenseRecord], notes: list[PlNoteLine], target_month: str) -> list[PlNoteLine]:
    """records を更新し、対象月の列でどの原本にも当たらなかったメモ明細を返す。"""
    used: set[int] = set()
    pending = [r for r in records if r.approval_status != Status.EXCLUDED]
    indexed = list(enumerate(notes))
    month_notes = [(i, n) for i, n in indexed if n.month_col == target_month]
    own = lambda r: [(i, n) for i, n in indexed if n.month_col in _own_months(r)]
    other = lambda r: [(i, n) for i, n in indexed if n.month_col not in _own_months(r)]

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
            own,
            lambda r, n: (
                n.amount == r.amount and _date_ok(r, n) and _sim(r, n) >= VENDOR_OK,
                _sim(r, n),
            ),
            PlMatch.MATCHED,
            Status.AUTO_MATCHED,
            lambda r, n: f"PL {n.cell}（{n.month_col}・{n.row_label}）のメモと利用先・日付・金額が一致",
        ),
        (
            own,
            lambda r, n: (n.amount == r.amount and _date_ok(r, n), 1.0),
            PlMatch.MATCHED,
            Status.REVIEW_REQUIRED,
            lambda r, n: f"PL {n.cell}（{n.row_label}）の「{n.vendor_raw or n.description}」と日付・金額は一致、利用先名が違う＝同一か確認",
        ),
        (
            own,
            lambda r, n: (
                _date_ok(r, n) and _sim(r, n) >= VENDOR_OK,
                -abs((n.amount or 0) - r.amount),
            ),
            PlMatch.AMOUNT_DIFF,
            Status.REVIEW_REQUIRED,
            lambda r, n: f"PL {n.cell}（{n.row_label}）のメモは {n.amount:,}円、原本は {r.amount:,}円＝差 {r.amount - n.amount:,}円",
        ),
        (
            other,
            lambda r, n: (
                n.amount == r.amount and _date_ok(r, n) and _sim(r, n) >= VENDOR_OK,
                _sim(r, n),
            ),
            PlMatch.MONTH_DIFF,
            Status.REVIEW_REQUIRED,
            lambda r, n: f"利用月・翌月ではなく {n.month_col}列の PL {n.cell}（{n.row_label}）に計上されている",
        ),
    ]

    for pool, cond, pl_status, status, reason in stages:
        for rec in pending:
            if rec.pl_note_match_status != PlMatch.UNCHECKED:
                continue
            n = take(rec, pool(rec), cond)
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
            rec.judgement_reason = f"PL（利用月と翌月）のメモに該当なし＝未反映候補"
            rec.log(rec.approval_status.value, rec.judgement_reason)

    return [n for i, n in month_notes if i not in used]


def _month_of_cell(rec: ExpenseRecord) -> str | None:
    """本部タブのセル（例 K16）→ 月列。見出し行は D=1月 … O=12月。"""
    if not rec.pl_cell:
        return None
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

    col, _ = coordinate_from_string(rec.pl_cell)
    m = column_index_from_string(col) - 3
    return f"{m}月" if 1 <= m <= 12 else None


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
        # 店舗タブは本部メモと同じ月列を見る（本部が付け替えた月＝店舗に載る月）
        month = _month_of_cell(rec) or target_month
        options = []
        for dept, notes in store_notes.items():
            cands = [
                n for n in notes
                if n.month_col == month and n.row_label == label and n.amount and n.amount > 0
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
