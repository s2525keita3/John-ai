"""
承認済みの行だけをPL（収支計画スプシ）へ書き込む（要件定義 §12）。

守ること：
- 書くのは「承認」「修正」された行だけ。差異が残る行・未確認の行は書かない。
- 数式のセルには書かない（本部経費の参照式などを壊さないため）。
- 書く直前にセルを読み直し、画面で見た旧値から変わっていたら書かない（他の人の編集と衝突しない）。
- メモは末尾に1行足すだけ。既存の行は消さない・書き換えない。
- 書いたあと読み直して、値とメモが狙いどおりか確かめる。
書き込み用の権限（spreadsheets スコープ）はこのモジュールだけが使う。読み取りは pl_source（読み取り専用）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from .models import ExpenseRecord, PlMatch
from .pl_source import PL_SPREADSHEET_ID, Grid, resolve_titles

SCOPES_RW = ["https://www.googleapis.com/auth/spreadsheets"]


@dataclass
class Change:
    record_id: str
    sheet: str
    cell: str
    old_value: float | None
    delta: int
    note_line: str
    reason: str
    blocked: str = ""  # 空でなければ書かない理由

    @property
    def new_value(self) -> float | None:
        return None if self.old_value is None else self.old_value + self.delta


@dataclass
class ApplyResult:
    change: Change
    ok: bool
    message: str
    after_value: float | None = None
    at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def _rc(coord: str) -> tuple[int, int]:
    col, row = coordinate_from_string(coord)
    return row, column_index_from_string(col)


def memo_line(r: ExpenseRecord, amount: int, content: str = "") -> str:
    """§3.1 の標準形：日付・科目・相手先・内容・（空）・金額。"""
    d = r.transaction_date.strftime("%y/%m/%d") if r.transaction_date else ""
    return "\t".join([d, r.expense_category, r.vendor_raw.strip(), content, "", f"{amount:,}"])


def plan_changes(records: list[ExpenseRecord], decisions: dict, grid: Grid, targets: dict[str, str] | None = None) -> list[Change]:
    """
    承認済みの行 → 書き込み案。
    targets：PL未反映の行に人が選んだ反映先セル（record_id → "K16" など）。
    """
    targets = targets or {}
    out: list[Change] = []
    for r in records:
        dec = decisions.get(r.id)
        if not dec or dec.get("action") not in ("承認", "修正"):
            continue
        if r.pl_note_match_status == PlMatch.AMOUNT_DIFF and r.pl_cell:
            cell = r.pl_cell
            delta = r.amount - (r.pl_amount or 0)
            line = memo_line(r, delta, f"（差額修正）原本 {r.amount:,}円／既存メモ {r.pl_amount:,}円")
            reason = "金額差異を承認（原本の金額に合わせる）"
        elif r.pl_note_match_status == PlMatch.NOT_IN_PL and targets.get(r.id):
            cell = targets[r.id]
            delta = r.amount
            line = memo_line(r, r.amount)
            reason = "PL未反映を承認（反映先を人が選択）"
        else:
            continue
        rr, cc = _rc(cell)
        old = grid.value(rr, cc)
        blocked = ""
        if isinstance(old, str) and old.startswith("="):
            blocked = "数式のセルなので書き込まない"
        elif old is not None and not isinstance(old, (int, float)):
            blocked = "数値でないセルなので書き込まない"
        out.append(Change(r.id, grid.title, cell, float(old) if isinstance(old, (int, float)) else (0.0 if old is None else None),
                          delta, line, reason, blocked))
    return out


def _service(sa_info: dict):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES_RW)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _read_cell(svc, spreadsheet_id: str, title: str, cell: str) -> tuple[object, str]:
    resp = svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        ranges=[f"'{title}'!{cell}"],
        includeGridData=True,
        fields="sheets(data(rowData(values(note,userEnteredValue,effectiveValue))))",
    ).execute()
    try:
        v = resp["sheets"][0]["data"][0]["rowData"][0]["values"][0]
    except (KeyError, IndexError):
        return None, ""
    uev = v.get("userEnteredValue", {})
    if "formulaValue" in uev:
        return uev["formulaValue"], v.get("note", "")
    return v.get("effectiveValue", {}).get("numberValue"), v.get("note", "")


def apply_changes(sa_info: dict, changes: list[Change], spreadsheet_id: str = PL_SPREADSHEET_ID) -> list[ApplyResult]:
    svc = _service(sa_info)
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)").execute()
    ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    results: list[ApplyResult] = []
    for ch in changes:
        if ch.blocked:
            results.append(ApplyResult(ch, False, ch.blocked))
            continue
        title = resolve_titles(list(ids), [ch.sheet]).get(ch.sheet)
        if title is None:
            results.append(ApplyResult(ch, False, f"タブ「{ch.sheet}」が見つからない"))
            continue
        cur, note = _read_cell(svc, spreadsheet_id, title, ch.cell)
        if isinstance(cur, str):
            results.append(ApplyResult(ch, False, "書く直前に見たら数式になっていたので中止"))
            continue
        if (cur or 0) != (ch.old_value or 0):
            results.append(ApplyResult(ch, False, f"画面で見た旧値 {ch.old_value:,.0f} から {cur or 0:,.0f} に変わっていたので中止（読み直してやり直す）"))
            continue
        new_note = (note.rstrip("\n") + "\n" + ch.note_line) if note.strip() else ch.note_line
        r, c = _rc(ch.cell)
        svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"updateCells": {
                "range": {"sheetId": ids[title], "startRowIndex": r - 1, "endRowIndex": r,
                          "startColumnIndex": c - 1, "endColumnIndex": c},
                "rows": [{"values": [{"userEnteredValue": {"numberValue": ch.new_value}, "note": new_note}]}],
                "fields": "userEnteredValue,note",
            }}]},
        ).execute()
        after, after_note = _read_cell(svc, spreadsheet_id, title, ch.cell)
        ok = after == ch.new_value and after_note.endswith(ch.note_line)
        results.append(ApplyResult(ch, ok, "書き込み・読み直し確認OK" if ok else "書いたが読み直しで一致しない（要確認）", after))
    return results
