"""
PL点検（ルールブック §10.3 ⑤ 反映前チェック）。収支計画スプシを読むだけで、書き込まない。

点検すること：
  A. セル＝メモ合計（「相殺」と書いた行は合計から除く＝桜木町の本部への駐車場貸出）
  B. メモの形（金額のない行・銀行の残高列が残った行）
  C. 付け替え5点が4店舗そろっているか
  D. 本部タブに請求の総額（SoftBank など）が入っていないか
  E. 本部経費の按分：行名の人数・率と式の率、所属人数÷(店舗計＋本部3) の一致
  F. 店舗の本部経費（26行）の実績が本部タブを参照しているか
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .departments import DEPARTMENTS, HQ_SHEET, STORES, plan_actual_month_map
from .pl_notes import _num, _parse_line, month_columns
from .pl_source import Grid

HQ_FIXED_HEADCOUNT = 3  # 本部はいつも3名（渋谷決定 2026-09-22）
HQ_ALLOC_ROWS = {"桜木町": 27, "新子安": 28, "白根": 29, "さいわい": 30}
STORE_ALLOC_ROW = 26
SKIP_ROWS = ("稼働率",)  # メモが注記のみで金額ではない行

RECHARGES = {  # 付け替え5点：(PL行の先頭語, 探す語)
    "SoftBank": ("通信費", r"softbank|ソフトバンク|携帯電話|スマホ"),
    "朝日ネット": ("通信費", r"朝日ネット|フレッツ"),
    "日新火災": ("保険料", r"日新火災|自動車保険"),
    "エネクスフリート": ("旅費", r"エネクス|エネフリ"),
    "中退共": ("退職金", r"退職金共済|中退共"),
}


@dataclass
class Finding:
    level: str  # 要対応／注意
    check: str
    dept: str
    cell: str
    detail: str


def _month_map(dept, g: Grid) -> dict[int, str]:
    return plan_actual_month_map() if dept.layout == "plan_actual" else {c: m for m, c in month_columns(g).items()}


def _col_for(dept, g: Grid, month: str) -> int | None:
    return next((c for c, m in _month_map(dept, g).items() if m == month), None)


def _row_of(g: Grid, prefix: str) -> int | None:
    for r in range(1, g.max_row + 1):
        v = g.value(r, 2)
        if isinstance(v, str) and v.strip().startswith(prefix):
            return r
    return None


def check_pl(grids: dict[str, Grid], month: str) -> list[Finding]:
    out: list[Finding] = []
    for d in DEPARTMENTS:
        g = grids.get(d.sheet)
        if g is None:
            out.append(Finding("要対応", "読み取り", d.name, "", f"タブ「{d.sheet}」を読めない"))
            continue
        col = _col_for(d, g, month)
        if col is None:
            continue
        for r in range(1, g.max_row + 1):
            note = g.note(r, col)
            label = str(g.value(r, 2) or "").strip()
            if not note or label.startswith(SKIP_ROWS):
                continue
            cell = Grid.coord(r, col)
            lines = [t for t in note.splitlines() if t.strip()]
            total = 0
            for t in lines:
                amt = _parse_line(t, 2026)[4]
                nums = [n for n in (_num(f) for f in t.split("\t")[1:]) if n is not None]
                if amt is None:
                    out.append(Finding("注意", "B メモの形", d.name, cell, f"{label}：金額のない行「{t.strip()[:40]}」"))
                elif len(nums) >= 2 and nums[-1] > nums[0] * 3:
                    out.append(Finding("注意", "B メモの形", d.name, cell, f"{label}：右端に残高らしき数字（{nums[-1]:,}）。金額は {nums[0]:,} として読んだ"))
                if amt and "相殺" not in t:
                    total += amt
            v = g.value(r, col)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v - total) >= 1:
                out.append(Finding("要対応", "A セル＝メモ合計", d.name, cell, f"{label}：セル {v:,.0f}／メモ合計 {total:,}（差 {v - total:,.0f}）"))

        if d.layout == "plan_actual":
            for item, (row_prefix, pat) in RECHARGES.items():
                r = _row_of(g, row_prefix)
                if r and not re.search(pat, g.note(r, col), re.I):
                    how = "→ 金額は推測しない。本部事務に店舗別の掛金を確認して埋める" if item == "中退共" else ""
                    out.append(Finding("要対応", "C 付け替え", d.name, Grid.coord(r, col), f"{item} が{row_prefix}のメモにない{how}"))
            v26 = g.value(STORE_ALLOC_ROW, col)
            want = f"'{HQ_SHEET}'!"
            if not (isinstance(v26, str) and v26.replace(" ", "").startswith(f"={want}")):
                out.append(Finding("注意", "F 本部経費の参照", d.name, Grid.coord(STORE_ALLOC_ROW, col),
                                   f"実績が本部タブの参照式ではない（今：{str(v26)[:30]}）"))
        else:
            r = _row_of(g, "通信費")
            for t in (g.note(r, col).splitlines() if r else []):
                amt = _parse_line(t, 2026)[4]
                if amt and amt >= 100_000 and re.search(RECHARGES["SoftBank"][1], t, re.I):
                    out.append(Finding("要対応", "D 本部分だけ", d.name, Grid.coord(r, col), f"SoftBank {amt:,} が本部に入っている（店舗分を含む総額の可能性）"))

    if month == latest_month(grids):
        # 行名の人数は「今の人数」なので、按分の点検は最新月だけ（過去月は当時の人数で正しい）
        out += _check_allocation(grids, month)
    return out


def latest_month(grids: dict[str, Grid]) -> str | None:
    """本部タブで人件費（7行）に数値が入っている最後の月＝締め対象の最新月。"""
    hq = grids.get(HQ_SHEET)
    if hq is None:
        return None
    last = None
    for m, c in sorted(month_columns(hq).items(), key=lambda x: x[1]):
        if isinstance(hq.value(7, c), (int, float)) and hq.value(7, c):
            last = m
    return last


def _check_allocation(grids: dict[str, Grid], month: str) -> list[Finding]:
    out: list[Finding] = []
    hq = grids.get(HQ_SHEET)
    if hq is None:
        return out
    hq_col = month_columns(hq).get(month)
    counts, rates = {}, {}
    for d in STORES:
        g = grids.get(d.sheet)
        if g is None:
            continue
        m = re.search(r"(\d+)名で([\d.]+)%", str(g.value(STORE_ALLOC_ROW, 2) or ""))
        f = str(hq.value(HQ_ALLOC_ROWS[d.name], hq_col) or "") if hq_col else ""
        fm = re.search(r"\*([\d.]+)%", f)
        if not m or not fm:
            out.append(Finding("要対応", "E 按分", d.name, "", "行名の人数・率、または本部タブの按分式が読めない"))
            continue
        counts[d.name], label_rate, rates[d.name] = int(m.group(1)), float(m.group(2)), float(fm.group(1))
        if abs(label_rate - rates[d.name]) >= 0.05:
            out.append(Finding("要対応", "E 按分", d.name, f"B{STORE_ALLOC_ROW}",
                               f"行名の率 {label_rate}% と本部タブ{month}の式の率 {rates[d.name]}% が違う"))
    if len(counts) == len(STORES):
        denom = sum(counts.values()) + HQ_FIXED_HEADCOUNT
        for name, n in counts.items():
            expect = round(n / denom * 100, 1)
            if abs(expect - rates[name]) >= 0.05:
                out.append(Finding("要対応", "E 按分", name, "",
                                   f"{n}名÷（店舗計{sum(counts.values())}＋本部{HQ_FIXED_HEADCOUNT}＝{denom}）＝{expect}% だが式は {rates[name]}%"))
    return out
