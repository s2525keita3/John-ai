"""PL点検（ルールブック §10 ⑤）。実データ不要の小さな表で確かめる。"""
from expense_hub.pl_check import check_pl
from expense_hub.pl_source import Grid

Z = 26  # 店舗タブ 8月実績列
K = 11  # 本部タブ 8月列


def _hq(people_rates=(34.8, 19.6, 26.1, 13.0)):
    g = Grid("2026年本部")
    g.cells[(2, K)] = ("8月", "")
    g.cells[(7, 2)] = ("人件費", "")
    g.cells[(7, K)] = (1_000_000, "")
    g.cells[(16, 2)] = ("通信費", "")
    g.cells[(16, K)] = (15_614, "26/07/31\t通信費\tソフトバンクＭ\t\t\t15,614")
    for i, rate in enumerate(people_rates):
        g.cells[(27 + i, K)] = (f"=K26*{rate}%*-1", "")
    g.max_row, g.max_column = 40, 15
    return g


def _store(title, label26, extra=None):
    g = Grid(title)
    rows = {
        26: (label26, "='2026年本部'!K27", ""),
        27: ("退職金積み立て（中小企業退職金共済）", 70_000, "26/08/27\t退職金積み立て\t代表口座\t中小企業退職金共済事業本部 8月掛け金\t\t70,000"),
        28: ("旅費交通費", 150_064, "26/08/27\t旅費交通費\t代表口座\tエネクスフリート 燃料代金7月分\t\t150,064"),
        32: ("通信費", 48_356, "26/08/27\t通信費\t代表口座\tSoftbankスマホ利用料 7月分\t\t45,202\n26/08/27\t通信費\t代表口座\t朝日ネット フレッツ光\t\t3,154"),
        37: ("保険料", 74_710, "26/08/27\t保険料\t代表口座\t日新火災海上保険 7月分\t\t74,710"),
    }
    rows.update(extra or {})
    for r, (label, v, note) in rows.items():
        g.cells[(r, 2)] = (label, "")
        g.cells[(r, Z)] = (v, note)
    g.max_row, g.max_column = 44, 40
    return g


def _grids(**over):
    g = {
        "2026年本部": _hq(),
        "桜：収支": _store("桜：収支", "本部経費（16名で34.8%）"),
        "新：収支": _store("新：収支", "本部経費（9名で19.6%）"),
        "白：収支": _store("白：収支", "本部経費（12名で26.1%）"),
        "さい：収支": _store("さい：収支", "本部経費（6名で13.0%）"),
    }
    g.update(over)
    return g


def test_clean_month_has_no_findings():
    assert check_pl(_grids(), "8月") == []


def test_offset_line_is_excluded_from_total():
    # 桜木町：本部へ貸した駐車場（相殺）はメモに書くが合計に入れない
    rent = {31: ("地代家賃", 20_000, "26/08/26\t賃借料\t大家\t事務所駐車場\t\t20,000\n26/08/26\t賃借料\t代表口座\t駐車場1台を本部へ貸出（本部管理費から相殺）\t\t13,530")}
    assert check_pl(_grids(**{"桜：収支": _store("桜：収支", "本部経費（16名で34.8%）", rent)}), "8月") == []


def test_missing_recharge_and_memo_mismatch():
    no_sb = {32: ("通信費", 48_356, "26/08/27\t通信費\t代表口座\t朝日ネット フレッツ光\t\t3,154")}
    f = check_pl(_grids(**{"さい：収支": _store("さい：収支", "本部経費（6名で13.0%）", no_sb)}), "8月")
    kinds = {(x.check, x.dept) for x in f}
    assert ("C 付け替え", "さいわい") in kinds
    assert ("A セル＝メモ合計", "さいわい") in kinds


def test_balance_column_is_flagged():
    bal = {31: ("地代家賃", 175_000, "26/06/26\t賃借料\t大家\t事務所家賃\t\t175,000\t1,920,051")}
    f = check_pl(_grids(**{"さい：収支": _store("さい：収支", "本部経費（6名で13.0%）", bal)}), "8月")
    assert any(x.check == "B メモの形" and "残高" in x.detail for x in f)
    assert not any(x.check == "A セル＝メモ合計" for x in f)


def test_allocation_label_vs_formula():
    g = _grids(**{"2026年本部": _hq((33.3, 22.2, 26.7, 11.1))})
    f = [x for x in check_pl(g, "8月") if x.check == "E 按分"]
    assert f and all(x.level == "要対応" for x in f)


def test_hq_softbank_total_is_flagged():
    hq = _hq()
    hq.cells[(16, K)] = (181_593, "26/07/31\t通信費\tソフトバンクＭ\t\t\t181,593")
    f = check_pl(_grids(**{"2026年本部": hq}), "8月")
    assert any(x.check == "D 本部分だけ" for x in f)
