"""あおぞら除外フィルタ：店舗スタッフ給与の除外は店舗モードのときだけ効く。実データ不要。"""
import pandas as pd

from aozora_filters import filter_aozora_hq_noise


def _kept(rows, station):
    df = pd.DataFrame({"摘要": rows, "出金額": [1000] * len(rows)})
    return filter_aozora_hq_noise(df, summary_col="摘要", station=station)["摘要"].tolist()


def test_hq_mode_keeps_outsourcing_payee_with_sakuragicho_like_surname():
    # 本部口座の外注先（動画編集代行＝支払報酬）。桜木町の姓カナ「ナカ」に当たるが消してはいけない
    rows = [
        "振込 ラクテン ナカムラ シユウヘイ",
        "振込 トウカイロウキン ナカムラ シユウヘイ",
        "振込 カ）ユ－スポ",
    ]
    assert _kept(rows, station=None) == rows


def test_hq_mode_still_drops_common_noise():
    rows = [
        "振替 カ）ジヨン サクラギチヨウ",
        "振込 ミツビシユ－エフジエイ シブヤケイタ",
        "PE 横浜市",
        "ATM ゆうちょ 出金",
        "振込 ラクテン ナカムラ シユウヘイ",
    ]
    assert _kept(rows, station=None) == ["振込 ラクテン ナカムラ シユウヘイ"]


def test_default_station_is_hq():
    df = pd.DataFrame({"摘要": ["振込 ラクテン ナカムラ シユウヘイ"]})
    assert len(filter_aozora_hq_noise(df)) == 1


def test_sakuragicho_store_mode_still_drops_staff_salary():
    rows = ["振込 ヤマグチ サオリ", "振込 カ）ユ－スポ"]
    assert _kept(rows, station="桜木町") == ["振込 カ）ユ－スポ"]
