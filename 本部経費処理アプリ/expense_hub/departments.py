"""
部門とPLタブの対応（要件定義 §10）。

本部タブは見出し行に「1月」〜「12月」がある。店舗の収支タブは月見出しが無く、
D列から1か月3列（計画・実績・差異）で並ぶ＝m月の実績は 5+3(m-1) 列（8月=Z）。
"""
from __future__ import annotations

from dataclasses import dataclass

HQ_SHEET = "2026年本部"


@dataclass(frozen=True)
class Department:
    name: str
    sheet: str
    layout: str  # "header"=見出し行に月名／"plan_actual"=計画・実績・差異の3列並び


DEPARTMENTS = (
    Department("本部", HQ_SHEET, "header"),
    Department("桜木町", "桜：収支", "plan_actual"),
    Department("新子安", "新：収支", "plan_actual"),
    Department("白根", "白：収支", "plan_actual"),
    Department("さいわい", "さい：収支", "plan_actual"),
)
STORES = tuple(d for d in DEPARTMENTS if d.layout == "plan_actual")


def plan_actual_month_map() -> dict[int, str]:
    """店舗収支タブ：列番号 → 「m月」（実績列だけ）。"""
    return {5 + 3 * (m - 1): f"{m}月" for m in range(1, 13)}
