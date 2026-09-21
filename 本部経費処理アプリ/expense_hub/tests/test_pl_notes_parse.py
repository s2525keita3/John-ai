"""セルメモ1行の読み取り（ルールブック §3 の書き方の揺れ）。実データ不要。"""
from datetime import date

from expense_hub.pl_notes import _parse_line


def test_standard_line():
    d, cat, vendor, desc, amt = _parse_line("26/08/27\t通信費\tＬＩＮＥ公式アカウント\t\t\t5,500", 2026)
    assert (d, cat, vendor, amt) == (date(2026, 8, 27), "通信費", "ＬＩＮＥ公式アカウント", 5500)


def test_bank_paste_with_balance_takes_amount_not_balance():
    # さいわい6月：銀行明細を貼ると右端に残高が付く
    *_, amt = _parse_line("26/06/26\t賃借料\tカサハラ ユウト\t事務所家賃\t\t175,000\t1,920,051", 2026)
    assert amt == 175_000


def test_free_text_with_yen_suffix():
    *_, amt = _parse_line("支払手数料　2,783円", 2026)
    assert amt == 2_783


def test_free_text_without_amount():
    *_, amt = _parse_line("支払手数料", 2026)
    assert amt is None


def test_card_paste_with_processing_date():
    # 本部1〜2月：利用日｜処理日｜利用先｜金額
    d, cat, vendor, _, amt = _parse_line("2025/12/31\t2026/1/9\tソフトバンクＭ\t6,800", 2026)
    assert (d, cat, vendor, amt) == (date(2025, 12, 31), "", "ソフトバンクＭ", 6800)
