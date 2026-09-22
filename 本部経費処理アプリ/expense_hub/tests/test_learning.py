"""判断の学習（要件定義 §8.2）：2回連続で自動、例外で要確認に戻る。実データ不要。"""
from datetime import date

from expense_hub.learning import apply_learned, decision_row, learn
from expense_hub.models import ExpenseRecord, PlMatch, Status


def _rec(vendor="ＥＮＥＯＳ　東京都", amount=2000):
    return ExpenseRecord("x", "amex_csv", "f", "h", 2, date(2026, 8, 20), None, vendor, "ENEOS", amount,
                         pl_note_match_status=PlMatch.NOT_IN_PL, approval_status=Status.REVIEW_REQUIRED,
                         judgement_reason="PLのメモに該当なし")


def _dec(action, cat="旅費交通費", at="2026-07-01"):
    return {"action": action, "category": cat, "dept": "本部", "reviewer": "渋谷", "at": at}


def test_once_is_not_enough():
    rows = [decision_row(_rec(), _dec("承認"), "7月")]
    r = _rec()
    assert apply_learned([r], learn(rows)) == 0
    assert r.approval_status == Status.REVIEW_REQUIRED
    assert "前回の判断" in r.judgement_reason


def test_twice_becomes_auto():
    rows = [decision_row(_rec(), _dec("承認", at="2026-06-01"), "6月"), decision_row(_rec(), _dec("承認"), "7月")]
    r = _rec()
    assert apply_learned([r], learn(rows)) == 1
    assert r.approval_status == Status.AUTO_MATCHED
    assert r.expense_category == "旅費交通費"


def test_exception_resets_streak():
    rows = [
        decision_row(_rec(), _dec("承認", at="2026-05-01"), "5月"),
        decision_row(_rec(), _dec("承認", at="2026-06-01"), "6月"),
        decision_row(_rec(), _dec("修正", cat="車両運搬費", at="2026-07-01"), "7月"),
    ]
    r = _rec()
    assert apply_learned([r], learn(rows)) == 0  # 直近が違う判断なので連続1回＝自動にしない


def test_exclude_twice_excludes():
    rows = [decision_row(_rec(), _dec("除外", cat="", at="2026-06-01"), "6月"), decision_row(_rec(), _dec("除外", cat=""), "7月")]
    r = _rec()
    apply_learned([r], learn(rows))
    assert r.approval_status == Status.EXCLUDED


def test_learning_does_not_touch_auto_matched():
    rows = [decision_row(_rec(), _dec("除外", cat=""), "6月")] * 2
    r = _rec()
    r.approval_status = Status.AUTO_MATCHED
    apply_learned([r], learn(rows))
    assert r.approval_status == Status.AUTO_MATCHED


def test_approval_without_category_is_not_learned():
    rows = [decision_row(_rec(), _dec("承認", cat=""), "6月"), decision_row(_rec(), _dec("承認", cat=""), "7月")]
    r = _rec()
    r.expense_category = ""
    rows = [[*row[:5], "", *row[6:]] for row in rows]  # 科目欄を空に
    assert apply_learned([r], learn(rows)) == 0
