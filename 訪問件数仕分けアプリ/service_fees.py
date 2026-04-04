"""
利用料（10割）の定数と概算売上計算（介護保険の訪問看護区分）。

介護 = 高い方、支援（予防）= 安い方（画像の表に準拠）。

医療保険の訪問看護は、別表（医療保険）であり日曜起算・月初・同日2回目/3回目
などの条件が付く。暫定として「医療」件数×固定単価を概算売上に加算する（列「医療」がある場合）。
"""
from __future__ import annotations

import pandas as pd

# 介護（10割）— 訪問看護 I-1〜I-4（看護）、I-5系（療法士）
CARE_NURSE_I2 = 5_237
CARE_NURSE_I3 = 9_151
CARE_NURSE_I4 = 12_543

CARE_THERAP_P20 = 3_269  # I-5
CARE_THERAP_P40 = 6_538  # I-5×2
CARE_THERAP_P60 = 8_840  # I-5・2超

# 支援・介護予防（10割）— 安い方
SUP_NURSE_I2 = 5_015
SUP_NURSE_I3 = 8_829
SUP_NURSE_I4 = 12_120

SUP_THERAP_P20 = 3_158
SUP_THERAP_P40 = 6_316
SUP_THERAP_P60 = 4_737

# 医療保険（暫定・円/回）— 「医療」件数に掛けて概算売上へ加算
MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT = 9_000


def _cell_float(row: pd.Series, key: str) -> float:
    v = row.get(key, 0)
    if v is None:
        return 0.0
    try:
        if pd.isna(v):
            return 0.0
    except TypeError:
        pass
    try:
        x = float(v)
        return 0.0 if x != x else x
    except (TypeError, ValueError):
        return 0.0


def _blend(care: float, support: float, support_ratio: float) -> float:
    """support_ratio: 0=すべて介護料金, 1=すべて支援料金"""
    r = max(0.0, min(1.0, support_ratio))
    return (1.0 - r) * care + r * support


def estimate_row_revenue_yen(row: pd.Series, support_ratio: float) -> float:
    """
    1行（担当者）の概算利用料（円）。
    PDF から _vis2_s/_vis2_c 等があるときは、支援単価×支援件数＋介護単価×介護件数で計算する。
    それ以外（CSV 等）は support_ratio で介護・支援単価をブレンドする従来方式。
    看護は _vis3・列30/90、療法は _p60・列20/40 を使う（列60は表示用のため混同しない）。
    看護師・療法士は両方の積を合算。同行は加算しない。医療は add_revenue_columns 側で件数×暫定単価を加算。
    """
    r = support_ratio

    if "_vis2_s" in row.index and "_vis2_c" in row.index:
        v2s = _cell_float(row, "_vis2_s")
        v3s = _cell_float(row, "_vis3_s")
        v4s = _cell_float(row, "_vis4_s")
        v2c = _cell_float(row, "_vis2_c")
        v3c = _cell_float(row, "_vis3_c")
        v4c = _cell_float(row, "_vis4_c")
        p20s = _cell_float(row, "_p20_s")
        p40s = _cell_float(row, "_p40_s")
        p60s = _cell_float(row, "_p60_s")
        p20c = _cell_float(row, "_p20_c")
        p40c = _cell_float(row, "_p40_c")
        p60c = _cell_float(row, "_p60_c")

        nurse_yen = 0.0
        if v2s + v3s + v4s + v2c + v3c + v4c > 0:
            nurse_yen = (
                v2s * SUP_NURSE_I2
                + v3s * SUP_NURSE_I3
                + v4s * SUP_NURSE_I4
                + v2c * CARE_NURSE_I2
                + v3c * CARE_NURSE_I3
                + v4c * CARE_NURSE_I4
            )
        pt_yen = 0.0
        if p20s + p40s + p60s + p20c + p40c + p60c > 0:
            pt_yen = (
                p20s * SUP_THERAP_P20
                + p40s * SUP_THERAP_P40
                + p60s * SUP_THERAP_P60
                + p20c * CARE_THERAP_P20
                + p40c * CARE_THERAP_P40
                + p60c * CARE_THERAP_P60
            )
        return nurse_yen + pt_yen

    role = str(row.get("_職種", ""))
    v2 = float(row.get("30", 0) or 0)
    v4 = float(row.get("90", 0) or 0)
    p20 = float(row.get("20", 0) or 0)
    p40 = float(row.get("40", 0) or 0)

    if "_vis3" in row.index and pd.notna(row.get("_vis3")):
        v3 = float(row["_vis3"] or 0)
    elif role in ("看護師", "看護師・療法士"):
        v3 = float(row.get("60", 0) or 0)
    else:
        v3 = 0.0

    if "_p60" in row.index and pd.notna(row.get("_p60")):
        p60 = float(row["_p60"] or 0)
    elif role == "療法士":
        p60 = float(row.get("60", 0) or 0)
    else:
        p60 = 0.0

    nurse_yen = 0.0
    if v2 + v3 + v4 > 0:
        nurse_yen = (
            v2 * _blend(CARE_NURSE_I2, SUP_NURSE_I2, r)
            + v3 * _blend(CARE_NURSE_I3, SUP_NURSE_I3, r)
            + v4 * _blend(CARE_NURSE_I4, SUP_NURSE_I4, r)
        )

    pt_yen = 0.0
    if p20 + p40 + p60 > 0:
        pt_yen = (
            p20 * _blend(CARE_THERAP_P20, SUP_THERAP_P20, r)
            + p40 * _blend(CARE_THERAP_P40, SUP_THERAP_P40, r)
            + p60 * _blend(CARE_THERAP_P60, SUP_THERAP_P60, r)
        )

    return nurse_yen + pt_yen


def add_revenue_columns(df: pd.DataFrame, support_ratio: float) -> pd.DataFrame:
    """概算売上(円)・売上÷時間(円/h) を追加したコピーを返す。

    介護（支援/介護区分）の利用料に加え、列「医療」がある行は
    医療件数×MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT を概算売上に含める。
    """
    out = df.copy()
    revenues: list[float] = []
    prod: list[float] = []
    has_med = "医療" in out.columns
    for _, row in out.iterrows():
        rev = estimate_row_revenue_yen(row, support_ratio)
        if has_med:
            rev += _cell_float(row, "医療") * MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT
        total = round(rev)
        revenues.append(total)
        minutes = float(row.get("_分数合計", 0) or 0)
        hours = minutes / 60.0 if minutes > 0 else 0.0
        prod.append(round(total / hours) if hours > 0 else 0.0)

    out["概算売上(円)"] = revenues
    out["売上/時間(円/h)"] = prod
    return out
