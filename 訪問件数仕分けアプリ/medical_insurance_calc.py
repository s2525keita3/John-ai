"""
医療保険（訪問看護）利用料10割の概算。

前提（帳票の表に合わせたモデル）:
- 週は日曜始まり。
- 「月初」はその利用者について、その月の最初の「同日初回」訪問（1日1回目）に適用。
- 「2日目以降」は同月の2回目以降の同日初回訪問。
- 同日2回目・3回目は専用単価（週次・月初の区分より優先）。
- 週内の何回目かは「同日初回」訪問のみを週内で数える（同日2回目以降は週カウントに含めない）。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from medical_insurance_fees import (
    MED_FIRST_OF_MONTH_WEEK_DAY4_PLUS,
    MED_FIRST_OF_MONTH_WEEK_UP_TO3,
    MED_SAME_DAY_2ND_VISIT,
    MED_SAME_DAY_3RD_VISIT,
    MED_SUBSEQUENT_WEEK_DAY4_PLUS,
    MED_SUBSEQUENT_WEEK_UP_TO3,
)


@dataclass(frozen=True)
class MedicalVisitEvent:
    staff: str
    visit_date: date
    patient_key: str
    line_index: int
    raw_line: str = ""


def week_start_sunday(d: date) -> date:
    """月曜=0 … 日曜=6 の weekday に対し、その週の日曜日。"""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def compute_medical_insurance_fees(visits: list[MedicalVisitEvent]) -> dict[str, Any]:
    """
    医療訪問イベントから利用料10割（円）を合算する。

    Returns:
        total_yen, by_staff (担当者->円), rows (明細行), warnings (注意文)
    """
    warnings: list[str] = []
    if not visits:
        return {
            "total_yen": 0,
            "by_staff": {},
            "rows": [],
            "warnings": ["医療訪問の明細行を検出できませんでした。サマリーの「医療」件数のみのため、下記の厳密算定はできません。"],
            "visit_count": 0,
        }

    visits_sorted = sorted(visits, key=lambda v: (v.patient_key, v.visit_date, v.line_index))
    by_day: dict[tuple[str, date], list[MedicalVisitEvent]] = defaultdict(list)
    for v in visits_sorted:
        by_day[(v.patient_key, v.visit_date)].append(v)
    for k in by_day:
        by_day[k].sort(key=lambda v: v.line_index)

    # その月で初めて現れる「同日初回」訪問かどうか（利用者×年月）
    first_fod_month_seen: set[tuple[str, int, int]] = set()
    # 週内の「同日初回」訪問の通し番号（利用者×週の日曜）
    fod_week_ordinal: dict[tuple[str, date], int] = defaultdict(int)

    rows_out: list[dict[str, Any]] = []
    total_yen = 0
    by_staff: dict[str, int] = defaultdict(int)

    for v in sorted(visits, key=lambda v: (v.visit_date, v.line_index, v.patient_key)):
        pk = v.patient_key
        d = v.visit_date
        w0 = week_start_sunday(d)
        day_list = by_day[(pk, d)]
        idx_in_day = day_list.index(v) + 1

        if idx_in_day == 2:
            fee = MED_SAME_DAY_2ND_VISIT
            note = "同日2回目訪問"
        elif idx_in_day >= 3:
            fee = MED_SAME_DAY_3RD_VISIT
            note = "同日3回目訪問（2回目合算）"
        else:
            ym_key = (pk, d.year, d.month)
            is_first_fod_in_month = ym_key not in first_fod_month_seen
            if is_first_fod_in_month:
                first_fod_month_seen.add(ym_key)

            fod_week_ordinal[(pk, w0)] += 1
            ord_w = fod_week_ordinal[(pk, w0)]

            if is_first_fod_in_month:
                if ord_w <= 3:
                    fee = MED_FIRST_OF_MONTH_WEEK_UP_TO3
                else:
                    fee = MED_FIRST_OF_MONTH_WEEK_DAY4_PLUS
                note = f"月の初回（同日1回目）・週内{ord_w}回目"
            else:
                if ord_w <= 3:
                    fee = MED_SUBSEQUENT_WEEK_UP_TO3
                else:
                    fee = MED_SUBSEQUENT_WEEK_DAY4_PLUS
                note = f"2回目以降（同日1回目）・週内{ord_w}回目"

        total_yen += fee
        by_staff[v.staff] += fee
        rows_out.append(
            {
                "担当者": v.staff,
                "日付": d.isoformat(),
                "利用者": pk,
                "単価区分": note,
                "金額(円)": fee,
            }
        )

    return {
        "total_yen": int(total_yen),
        "by_staff": dict(by_staff),
        "rows": rows_out,
        "warnings": warnings,
        "visit_count": len(visits),
    }
