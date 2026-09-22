"""
判断の学習（要件定義 §8.2）。
渋谷さんの判断（承認・修正・除外）を台帳に残し、同じ利用先で同じ判断が2回続いたら次から自動確定にする。
例外（違う判断）が出たら、その利用先は要確認に戻す（連続回数を0に）。

 - 学習するのは「人が確定した判断」だけ。アプリの自動一致は学習しない（自分の出力を自分で強化しない）
 - 覚えるのは 利用先キー（正規化）→ 科目・部門・判断。金額は覚えない（毎月変わる）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import ExpenseRecord, PlMatch, Status
from .vendor import normalize_vendor

AUTO_AFTER = 2  # この回数、同じ判断が続いたら自動確定
DECISION_COLUMNS = ["at", "actor", "vendor_key", "vendor_raw", "action", "category", "department", "record_id", "month"]


@dataclass
class Learned:
    vendor_key: str
    action: str
    category: str
    department: str
    streak: int  # 直近で同じ判断が続いた回数
    last_at: str

    @property
    def auto(self) -> bool:
        return self.streak >= AUTO_AFTER and self.action in ("承認", "修正", "除外")


def decision_row(r: ExpenseRecord, dec: dict, month: str) -> list:
    return [
        dec.get("at") or datetime.now().isoformat(timespec="seconds"), dec.get("reviewer", ""),
        normalize_vendor(r.vendor_raw), r.vendor_raw.strip(), dec["action"],
        dec.get("category") or r.expense_category, dec.get("dept", ""), r.id, month,
    ]


def learn(rows: list[list]) -> dict[str, Learned]:
    """decisions の全行（古い順）→ 利用先ごとの学習結果。"""
    out: dict[str, Learned] = {}
    for row in rows:
        row = list(row) + [""] * (len(DECISION_COLUMNS) - len(row))
        at, _, key, _, action, cat, dept, _, _ = row[:9]
        if not key or action == "保留":
            continue
        if action in ("承認", "修正") and not cat:
            continue  # 科目が決まっていない承認（PL未反映で反映先を選ぶ前）は学習しない
        prev = out.get(key)
        same = prev and (prev.action, prev.category, prev.department) == (action, cat, dept)
        out[key] = Learned(key, action, cat, dept, (prev.streak + 1) if same else 1, at)
    return out


def apply_learned(records: list[ExpenseRecord], learned: dict[str, Learned]) -> int:
    """要確認の行に学習結果を当てる。自動確定した件数を返す。"""
    n = 0
    for r in records:
        if r.approval_status != Status.REVIEW_REQUIRED:
            continue
        L = learned.get(r.vendor_normalized)
        if not L or not L.auto:
            if L:
                r.judgement_reason += f"／前回の判断：{L.action}（{L.category}）"
            continue
        if L.action == "除外":
            r.approval_status = Status.EXCLUDED
            r.pl_note_match_status = PlMatch.NOT_APPLICABLE
        else:
            r.approval_status = Status.AUTO_MATCHED
            r.expense_category = L.category or r.expense_category
            r.department = L.department or r.department
        r.judgement_reason = f"学習済み（同じ判断が{L.streak}回連続）：{L.action}・{L.category}｜元の判定：{r.judgement_reason}"
        r.log("LEARNED", r.judgement_reason)
        n += 1
    return n
