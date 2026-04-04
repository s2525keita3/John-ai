"""
要件定義書 v2 の 2.2 自社PL勘定項目（ドロップダウン用）
"""
from __future__ import annotations

# 収入側
PL_INCOME = [
    "本部売上",
    "その他入金",
    "入金",
]

# 経費側（販管費）— 人件費は細目を分けて列挙
PL_EXPENSE = [
    "人件費(支給額,健康,介護,厚生,子ども)",  # 支給控除一覧の合計（タブ④）と揃える
    "人件費（支給額）",
    "人件費（健康）",
    "人件費（介護）",
    "人件費（厚生）",
    "人件費（子ども）",
    "賞与",
    "労働保険料",
    "他税金支払い",
    "退職金積み立て",
    "福利厚生",
    "旅費交通費",
    "接待交際費",
    "地代家賃",
    "通信費",
    "備品消耗品費",
    "車両運搬費",
    "水道光熱費",
    "保険料",
    "租税公課",
    "リース料",
    "雑費",
    "支払報酬",
    "返済",
]

# 集計・その他（必要に応じて振替で使う）
PL_SUMMARY = [
    "販管費合計",
    "残金",
    "返済費用",
    "コンサル使用経費",
    "全合計本部収支",
]

PL_ACCOUNTS_ALL: list[str] = PL_INCOME + PL_EXPENSE + PL_SUMMARY

# 経費振り分けで主に使う（ドロップダウンを短くしたい場合）
PL_ACCOUNTS_DEFAULT: list[str] = PL_EXPENSE + ["その他（要マスタ修正）"]


def pl_dropdown_options(full_list: bool) -> list[str]:
    """data_editor の Selectbox 用（先頭に未選択）"""
    base = PL_ACCOUNTS_ALL if full_list else PL_ACCOUNTS_DEFAULT
    return ["（未選択）"] + base
