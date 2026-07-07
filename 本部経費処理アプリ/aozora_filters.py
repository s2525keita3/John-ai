"""
あおぞらネット銀行（法人口座）CSV向けの振分除外（店舗別・本部運用ルール）。
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

STATION_NAMES = ("桜木町", "新子安", "白根", "さいわい")


def _norm(s: str) -> str:
    """全半角・スペースの揺れを吸収（classifier.normalize_for_match と同じ規則）。"""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", "", s).upper()


# 店舗別「スタッフ給与振込」の除外名義（フルネーム・正規化して部分一致）。
# 給与は支給控除一覧（人件費）側で把握するため、あおぞら明細からは除外して二重計上を防ぐ。
# 2026年の実CSV（GMOあおぞら statement-*.csv）の振込名義とスタッフ名簿を突き合わせて作成した。
# 名簿で確認できない名義はここに足さない（判断不能に出してオーナー確認に回す。
# 摘要の見た目で給与と推測しない — エイトプラス/イナミを誤除外した教訓）。
STATION_STAFF_FULLNAMES: dict[str, tuple[str, ...]] = {
    "白根": (
        "クサノセエイジ",      # 草ノ瀬英児（管理者）
        "イシバシチアキ",      # 石橋千明
        "ホリイユズキ",        # 堀井柚希
        "イトウマサシ",        # 伊藤雅士
        "モリリサ",            # 森里紗
        "タテユリア",          # 舘百合亜
        "ミシマシユウセイ",    # 三島柊生
        "サトウリヨウカ",      # 佐藤凌翔
        "フカヤトシユキ",      # 深谷敏行
        "ヨコヤママヤ",        # 横山摩耶
        "コバタケミヤコ",      # 小畠都（事務。白根・さいわい両口座から支給実績あり）
        "ナカノモエカ",        # 中野萌香（2026年1〜3月の給与振込実績。名簿(2026-05)以前の退職者）
    ),
    "新子安": (
        "ヤマザキミハル",      # 山崎未晴（管理者）
        "ヤマザキフミコ",      # 山崎文子
        "ツチヤナオコ",        # 土屋直子
        "シンバサヤカ",        # 榛葉紗也佳
        "オノデラトウヤ",      # 小野寺冬弥
        "オオヤマリサコ",      # 大山莉紗子
        "イノウエリヨウイチ",  # 井上遼一
        "アンドウユウマ",      # 安藤雄真
        "ゴトウケイコ",        # 後藤恵子（事務）
    ),
    "さいわい": (
        "モミヤマコウエイ",    # 籾山洸映（管理者）
        "シマブクロユキノ",    # 島袋結希乃
        "サトウアヤカ",        # 佐藤綾香
        "サワダメイ",          # 澤田芽依
        "ヤマザキユウダイ",    # 山崎雄大
        "イトウジユンヤマトンド",  # 伊藤隼也マトンド（時給）
        "タカハシコウスケ",    # 髙橋（2026年新入職・管理者候補）
        "ヒエダジユンヤ",      # 退職スタッフ（2026年1〜2月給与。オーナー確認済 2026-07-07）
        # 事務スタッフ給与は実CSVでさいわい口座からの支給を確認済み
        "ゴトウケイコ",        # 後藤恵子（新子安・事務）
        "コバタケミヤコ",      # 小畠都（白根・事務）
        "イシイユリ",          # 石井友梨（桜木町・事務）
    ),
}

# 桜木町は従来の姓カナ・生文字列部分一致を維持する。
# （2026年1〜7月の実CSV 423行で「除外後311行すべて確定」を検証済み。
#   正規化マッチに変えるとスペース除去で語境界が消え、誤除外が増え得るため触らない。）
_SAKURAGICHO_SURNAMES = (
    "ヤマグチ",
    "ミカミ",
    "マツ",
    "ナカ",
    "トクラ",
    "タナカ",
    "タカハシ",
    "スズキ",
    "ササキ",
    "オオツジ",
    "イシダミユキ",
    "イシイ",
    "サトウ",
)

# 店舗取り違え検知用（その店舗の明細にしか出ない中核スタッフのフルネーム）。
# 兼務・他店口座から支給される事務スタッフは入れない。
_STATION_SIGNATURE_NAMES: dict[str, tuple[str, ...]] = {
    "桜木町": (
        "ヤマグチサオリ",
        "ミカミカエデ",
        "トクラアヤノ",
        "タカハシユウスケ",
        "オオツジセイタ",
        "ササキユウマ",
    ),
    "白根": (
        "クサノセエイジ",
        "イシバシチアキ",
        "ホリイユズキ",
        "ミシマシユウセイ",
        "フカヤトシユキ",
        "ヨコヤママヤ",
    ),
    "新子安": (
        "ヤマザキミハル",
        "ツチヤナオコ",
        "シンバサヤカ",
        "オノデラトウヤ",
        "アンドウユウマ",
        "イノウエリヨウイチ",
    ),
    "さいわい": (
        "モミヤマコウエイ",
        "シマブクロユキノ",
        "サトウアヤカ",
        "サワダメイ",
        "ヤマザキユウダイ",
    ),
}


def count_station_signature_hits(summaries: pd.Series) -> dict[str, int]:
    """摘要一覧に各店舗の中核スタッフ名義が何行出るかを数える（CSVの店舗取り違え検知用）。"""
    normed = summaries.fillna("").astype(str).map(_norm)
    hits: dict[str, int] = {}
    for station, names in _STATION_SIGNATURE_NAMES.items():
        mask = pd.Series(False, index=normed.index)
        for name in names:
            mask = mask | normed.str.contains(name, regex=False)
        hits[station] = int(mask.sum())
    return hits


def detect_station_mismatch(summaries: pd.Series, station: str) -> str | None:
    """選択中の店舗より他店舗のスタッフ名義が多ければ、その店舗名を返す（警告表示用）。"""
    hits = count_station_signature_hits(summaries)
    own = hits.get(station, 0)
    other, n = max(
        ((s, c) for s, c in hits.items() if s != station),
        key=lambda t: t[1],
        default=(None, 0),
    )
    if other is not None and n >= 2 and n > own:
        return other
    return None


def _staff_salary_mask(summaries: pd.Series, station: str) -> pd.Series:
    """店舗スタッフへの給与振込らしき行の True マスク。"""
    if station == "桜木町":
        s = summaries.fillna("").astype(str)
        mask = pd.Series(False, index=s.index)
        for kw in _SAKURAGICHO_SURNAMES:
            mask = mask | s.str.contains(kw, regex=False)
        return mask
    names = STATION_STAFF_FULLNAMES.get(station, ())
    normed = summaries.fillna("").astype(str).map(_norm)
    mask = pd.Series(False, index=normed.index)
    for name in names:
        mask = mask | normed.str.contains(name, regex=False)
    return mask


def filter_aozora_hq_noise(
    df: pd.DataFrame, summary_col: str = "摘要", station: str = "桜木町"
) -> pd.DataFrame:
    """
    資金移動・支給控除と二重になる支出・エネフリで別途見る決済などを除外。

    全店舗共通:
    - 振替 カ）ジヨン…（口座間の資金移動）
    - 振込 ヨコハマシンキン カ）ジヨン（資金移動）
    - 三菱UFJ・シブヤケイタ（役員報酬／人件費は支給控除で把握）
    - ラクテン イシダユミエ（支給控除）
    - PE 地方税・税務署（電子納付）
    - 社会保険料（半角ｼﾔｶｲﾎｹﾝﾘﾖｳ等／支給控除）
    - ATM 出入金・手数料（小口補充・現金移動。小口入力側で明細化する）

    店舗別:
    - station のスタッフへの給与振込（支給控除側で把握するため除外。
      桜木町=姓カナ、白根・新子安・さいわい=名簿と実CSVで裏取りしたフルネーム）

    医療保険入金（国保連合会・支払基金など）は除外せず「入金」としてマスタ分類する。
    オリコ（全角・半角ｵﾘｺ）は filter_exclude_orico で除外。
    """
    if summary_col not in df.columns:
        return df
    s = df[summary_col].fillna("").astype(str)
    st = s.str.strip()

    drop = (
        (s.str.contains("振替", regex=False) & s.str.contains("カ）ジヨン", regex=False))
        | (s.str.contains("ヨコハマシンキン", regex=False) & s.str.contains("カ）ジヨン", regex=False))
        | s.str.contains("ミツビシユ－エフジエイ シブヤケイタ", regex=False)
        | s.str.contains("イシダユミエ", regex=False)
        | st.str.startswith("PE ")
        | s.str.contains("ｼﾔｶｲﾎｹﾝﾘﾖｳ", regex=False)
        | (s.str.contains("社会保険", regex=False) & ~s.str.contains("医療保険", regex=False))
        # 小口補充・現金移動（ATM出入金・手数料）は小口入力側で明細化するため除外
        # （桜木町=ゆうちょ／白根=セブン銀行など、店舗によりATM機関が異なるため機関は限定しない）
        | st.str.startswith("ATM")
        | _staff_salary_mask(s, station)
    )

    return df[~drop].copy()
