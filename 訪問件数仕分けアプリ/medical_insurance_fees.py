"""
医療保険（訪問看護）の利用料10割・算定の考え方（参照用定数）。

介護保険の「支援／介護」単価（service_fees）とは別体系。
週の区切りは日曜始まりで数える（起算日曜）。

明細行（医療区分・日付・利用者）がPDFから取れれば medical_insurance_calc で按分する。
取れない場合はサマリー件数のみ参照。
"""

from __future__ import annotations

# 月の初日の訪問（10割・円）
MED_FIRST_OF_MONTH_WEEK_UP_TO3 = 13_220  # 週3日まで
MED_FIRST_OF_MONTH_WEEK_DAY4_PLUS = 14_220  # 週4日以降

# 2日目以降の訪問（10割・円）
MED_SUBSEQUENT_WEEK_UP_TO3 = 8_550
MED_SUBSEQUENT_WEEK_DAY4_PLUS = 9_550

# 同日複数回
MED_SAME_DAY_2ND_VISIT = 4_500  # 同日 2回目訪問
MED_SAME_DAY_3RD_VISIT = 8_000  # 同日 3回目（表記は2回目合算）訪問
