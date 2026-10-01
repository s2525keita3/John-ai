"""マスタのデータソース区分が空欄の行は、どのデータソースでも効く（NaN を "nan" にしない）。"""
import io

from classifier import classify_row, load_master_csv

CSV = (
    "摘要キーワード,自社PL勘定項目,金額下限,金額上限,データソース区分\n"
    "振込手数料,雑費,,,\n"
    "アスクル,備品消耗品費,,,あおぞら（桜木町）\n"
)


def test_blank_source_rule_applies_with_source_filter():
    master = load_master_csv(io.StringIO(CSV))
    assert master[0].source == ""
    c, pl, _ = classify_row("振込手数料", 99, master, source_filter="あおぞら")
    assert (c, pl) == ("確定", "雑費")


def test_source_specific_rule_wins_tie_over_common_rule():
    csv = (
        "摘要キーワード,自社PL勘定項目,金額下限,金額上限,データソース区分\n"
        "シブヤ ケイタ,本部売上,,,\n"
        "シブヤ　ケイタ,入金,,,あおぞら\n"
    )
    master = load_master_csv(io.StringIO(csv))
    _, pl, _ = classify_row("振込  シブヤ　ケイタ", 10266, master, source_filter="あおぞら")
    assert pl == "入金"


def test_other_source_rule_still_filtered():
    master = load_master_csv(io.StringIO(CSV))
    c, _, _ = classify_row("アスクル", 500, master, source_filter="あおぞら")
    assert c == "判断不能"
