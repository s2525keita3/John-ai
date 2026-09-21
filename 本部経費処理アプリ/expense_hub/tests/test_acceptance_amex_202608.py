"""
受入テスト（要件定義 §16）：2026年8月のアメックスCSV × 収支計画PLのセルメモ。
実データはリポジトリに入れない。環境変数でパスを渡す：
  EXPENSE_AMEX_CSV=...activity (20).csv
  EXPENSE_PL_XLSX=...2026年 ステーション収支計画.xlsx（Sheetsからxlsxでエクスポート）
実行：py -3 -m pytest 本部経費処理アプリ/expense_hub/tests -q
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from expense_hub.ledger import DuplicateImport, Ledger
from expense_hub.models import PlMatch, Status
from expense_hub.pipeline import run, to_csv

AMEX = os.environ.get("EXPENSE_AMEX_CSV")
PL = os.environ.get("EXPENSE_PL_XLSX")
pytestmark = pytest.mark.skipif(not (AMEX and PL), reason="実データのパスが未設定")


@pytest.fixture
def result(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    res = run(Path(AMEX).read_bytes(), Path(AMEX).name, Path(PL).read_bytes(), "8月", ledger=ledger)
    return res, ledger, tmp_path


def _find(res, word):
    return [r for r in res.records if word in r.vendor_raw]


def test_totals(result):
    res, _, _ = result
    assert res.summary["経費総額"] == 441_388
    assert res.summary["除外額（口座振替等）"] == -425_852


def test_known_vendors_matched(result):
    res, _, _ = result
    for word in ("TASKAR", "アマゾン", "Ｓｕｉｃａ", "ＡＮＡ", "ANTHROPIC", "CHATGPT", "アドビ", "電力", "関内苑", "ハレツバメ", "鶴屋"):
        hits = _find(res, word)
        assert hits, word
        assert all(h.pl_note_match_status == PlMatch.MATCHED for h in hits), (word, [h.judgement_reason for h in hits])


def test_softbank_diff_explained_by_allocation(result):
    """本部メモ15,614円との差165,979円は、4店舗の通信費メモ（スマホ利用料）への按分で説明できる。"""
    res, _, _ = result
    sb = [r for r in _find(res, "ソフトバンク") if r.amount == 181_593][0]
    assert sb.pl_note_match_status == PlMatch.ALLOCATED
    assert sb.approval_status == Status.AUTO_MATCHED
    alloc = {a["department"]: a["amount"] for a in sb.allocation_lines}
    assert alloc == {"本部": 15_614, "桜木町": 45_202, "新子安": 45_372, "白根": 46_783, "さいわい": 28_622}
    assert sum(alloc.values()) == 181_593
    assert res.summary["差異額"] == 0


def test_no_review_left(result):
    res, _, _ = result
    assert [r for r in res.records if r.approval_status == Status.REVIEW_REQUIRED] == []


def test_amount_only_coincidence_stays_in_review():
    """金額だけ合って利用先名で裏付けできない按分は、自動確認にしない。"""
    from datetime import date
    from expense_hub.matcher import match_allocations
    from expense_hub.models import ExpenseRecord, PlNoteLine

    rec = ExpenseRecord("x", "amex_csv", "f", "h", 2, date(2026, 7, 31), None, "ソフトバンクＭ", "ソフトバンクM", 1000,
                        expense_category="通信費", pl_sheet="2026年本部", pl_cell="K16", pl_amount=400,
                        pl_note_match_status=PlMatch.AMOUNT_DIFF, approval_status=Status.REVIEW_REQUIRED)
    other = PlNoteLine("桜：収支", "Z32", "通信費", "8月", 1, "26/08/27	通信費	NTT	光回線		600", date(2026, 8, 27),
                       "通信費", "NTT", "NTT", "光回線", 600)
    match_allocations([rec], {"桜木町": [other]}, "8月")
    assert rec.pl_note_match_status == PlMatch.AMOUNT_DIFF
    assert rec.approval_status == Status.REVIEW_REQUIRED
    assert "按分候補" in rec.judgement_reason


def test_reimport_rejected(result):
    res, ledger, _ = result
    with pytest.raises(DuplicateImport):
        ledger.save_import("amex_csv", "again.csv", res.source_file_hash, "8月", res.records)
    again = run(Path(AMEX).read_bytes(), "again.csv", Path(PL).read_bytes(), "8月", ledger=ledger)
    assert again.duplicate_of is not None


def test_backup_and_csv(result):
    res, ledger, tmp = result
    p = ledger.backup_pl(Path(PL).read_bytes(), "8月", tmp / "backup")
    assert p.exists() and p.stat().st_size > 0
    out = to_csv(res.records).decode("utf-8-sig").splitlines()
    assert out[0].startswith("原本行,利用日")
    assert len(out) == 1 + 18
