"""
「2026年 ステーション収支計画」の各セルのメモ（Sheetsのノート）を明細に分解する。
xlsx でエクスポートすると Sheets のノートは openpyxl の comment として読める。

メモ1行の形（タブ区切り）：
  26/08/01 <TAB> 通信費 <TAB> 相手先 <TAB> 内容 <TAB> (空) <TAB> 金額
PLの値・メモは読むだけで、ここでは絶対に書き換えない。
"""
from __future__ import annotations

import re
from datetime import date

from .models import PlNoteLine
from .pl_source import Grid
from .vendor import normalize_vendor

DEFAULT_SHEET = "2026年本部"
_DATE = re.compile(r"^\s*(\d{2,4})/(\d{1,2})/(\d{1,2})")
_NUM = re.compile(r"^-?[\d,]+$")


def _parse_date(s: str, default_year: int) -> date | None:
    m = _DATE.match(s)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _parse_line(text: str, default_year: int) -> tuple[date | None, str, str, str, int | None]:
    fields = [f.strip() for f in text.split("\t")]
    nums = [f for f in fields if _NUM.match(f)]
    amount = int(nums[-1].replace(",", "")) if nums else None
    d = _parse_date(fields[0], default_year) if fields else None
    if d is None:
        # 「支払手数料　814」のような自由記述：末尾の数字だけ拾う
        m = re.search(r"(-?[\d,]+)\s*$", text)
        amount = int(m.group(1).replace(",", "")) if m and amount is None else amount
        return None, "", "", text.strip(), amount
    rest = [f for f in fields[1:] if f and not _NUM.match(f)]
    category = rest[0] if len(rest) > 0 else ""
    vendor = rest[1] if len(rest) > 1 else ""
    desc = " ".join(rest[2:])
    return d, category, vendor, desc, amount


def month_columns(g: Grid, header_row: int = 2) -> dict[str, int]:
    """見出し行（「1月」〜「12月」）→ 列番号。"""
    out = {}
    for c in range(1, g.max_column + 1):
        v = g.value(header_row, c)
        if isinstance(v, str) and re.fullmatch(r"\d{1,2}月", v.strip()):
            out[v.strip()] = c
    return out


def read_note_lines(
    g: Grid, year: int = 2026, label_col: int = 2, month_map: dict[int, str] | None = None
) -> list[PlNoteLine]:
    """month_map（列番号→「m月」）を渡さなければ見出し行から月列を探す。"""
    months = month_map or {c: m for m, c in month_columns(g).items()}
    lines: list[PlNoteLine] = []
    for (r, c) in sorted(g.cells):
        note = g.note(r, c)
        if not note or c not in months:
            continue
        label = g.value(r, label_col) or ""
        for i, text in enumerate(note.splitlines(), start=1):
            if not text.strip():
                continue
            d, cat, vendor, desc, amt = _parse_line(text, year)
            lines.append(
                PlNoteLine(
                    sheet=g.title,
                    cell=Grid.coord(r, c),
                    row_label=str(label).strip(),
                    month_col=months[c],
                    line_no=i,
                    raw=text,
                    date=d,
                    category=cat,
                    vendor_raw=vendor,
                    vendor_normalized=normalize_vendor(vendor),
                    description=desc,
                    amount=amt,
                )
            )
    return lines


def cell_note_totals(g: Grid, month: str, label_col: int = 2) -> list[dict]:
    """セル値とメモ明細合計の突合（合算計上・メモ漏れの検出用）。"""
    col = month_columns(g).get(month)
    if col is None:
        return []
    out = []
    for r in range(1, g.max_row + 1):
        note = g.note(r, col)
        if not note:
            continue
        total = sum((_parse_line(t, 2026)[4] or 0) for t in note.splitlines() if t.strip())
        val = g.value(r, col)
        val = val if isinstance(val, (int, float)) and not isinstance(val, bool) else None
        out.append(
            {
                "cell": Grid.coord(r, col),
                "row_label": str(g.value(r, label_col) or "").strip(),
                "cell_value": val,
                "note_total": total,
                "diff": (val - total) if val is not None else None,
            }
        )
    return out
