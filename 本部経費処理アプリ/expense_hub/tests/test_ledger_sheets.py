"""台帳スプシ版（SheetsLedger）。通信はせず、Sheets API の形だけ真似た偽物で確かめる。"""
import hashlib
from datetime import date
from types import SimpleNamespace

import pytest

from expense_hub.ledger import SHEET_COLUMNS, DuplicateImport, Ledger, SheetsLedger, get_ledger
from expense_hub.models import ExpenseRecord


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeSheets:
    """spreadsheets().get / batchUpdate / values().get / batchGet / batchUpdate / append だけの偽物。"""

    def __init__(self, tabs=()):
        self.tabs: dict[str, list[list]] = {t: [] for t in tabs}

    # spreadsheets()
    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, fields=""):
        return _Req(lambda: {"sheets": [{"properties": {"title": t}} for t in self.tabs]})

    def batchUpdate(self, spreadsheetId, body):
        def run():
            for r in body["requests"]:
                self.tabs[r["addSheet"]["properties"]["title"]] = []
            return {}
        return _Req(run)

    def values(self):
        return _Values(self)


class _Values:
    def __init__(self, fake: FakeSheets):
        self.f = fake

    def get(self, spreadsheetId, range):
        tab = range.split("!")[0]
        return _Req(lambda: {"values": [list(map(str, r)) for r in self.f.tabs[tab][1:]]})

    def batchGet(self, spreadsheetId, ranges):
        return _Req(lambda: {"valueRanges": [
            {"values": self.f.tabs[r.split("!")[0]][:1]} if self.f.tabs[r.split("!")[0]] else {} for r in ranges
        ]})

    def batchUpdate(self, spreadsheetId, body):
        def run():
            for d in body["data"]:
                rows = self.f.tabs[d["range"].split("!")[0]]
                rows[:1] = d["values"]
            return {}
        return _Req(run)

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        assert valueInputOption == "RAW"
        return _Req(lambda: self.f.tabs[range.split("!")[0]].extend(body["values"]) or {})


def _rec(i: int, h: str = "h1") -> ExpenseRecord:
    r = ExpenseRecord(
        id=f"r{i}", source_type="amex", source_file_id="activity.csv", source_file_hash=h,
        source_row_number=i, transaction_date=date(2026, 8, i), processing_date=None, vendor_raw="テスト", vendor_normalized="テスト",
        amount=1000 * i,
    )
    r.log("IMPORT", "取込")
    return r


def test_タブと見出しを作る():
    fake = FakeSheets(tabs=["Sheet1"])
    SheetsLedger(fake, "X")
    for t, cols in SHEET_COLUMNS.items():
        assert fake.tabs[t] == [cols]
    SheetsLedger(fake, "X")  # 2回目は見出しを重ねない
    assert fake.tabs["records"] == [SHEET_COLUMNS["records"]]


def test_同じ原本は二重取込しない():
    fake = FakeSheets()
    led = SheetsLedger(fake, "X")
    assert led.already_imported("h1") is None
    led.save_import("amex", "activity.csv", "h1", "8月", [_rec(1), _rec(2)])
    got = led.already_imported("h1")
    assert got["filename"] == "activity.csv" and got["imported_at"]
    assert len(fake.tabs["records"]) == 3 and len(fake.tabs["audit_log"]) == 3
    with pytest.raises(DuplicateImport):
        led.save_import("amex", "activity.csv", "h1", "8月", [_rec(1)])
    assert len(fake.tabs["import_batches"]) == 2  # 見出し＋1件のまま
    # 再起動（新しいインスタンス）でも覚えている
    assert SheetsLedger(fake, "X").already_imported("h1")


def test_更新は追記で最新行が勝つ():
    fake = FakeSheets()
    led = SheetsLedger(fake, "X")
    r = _rec(1)
    led.save_import("amex", "a.csv", "h1", "8月", [r])
    r.log("REVIEW:承認", "科目=通信費", actor="渋谷")
    led.update(r, "8月")
    rows = [x for x in fake.tabs["records"][1:] if x[0] == "r1"]
    assert len(rows) == 2
    assert fake.tabs["audit_log"][-1][1:4] == ["渋谷", "r1", "REVIEW:承認"]
    assert r.audit_log == []


def test_PL書き込みログ():
    fake = FakeSheets()
    led = SheetsLedger(fake, "X")
    ch = SimpleNamespace(record_id="r1", sheet="2026年本部", cell="K16", old_value=100.0, new_value=250.0,
                         note_line="26/08/01\t通信費\tA\t\t\t150")
    led.log_write("渋谷", SimpleNamespace(change=ch, at="2026-09-22T10:00:00", ok=True, message="書いた"))
    assert fake.tabs["pl_writes"][-1] == ["2026-09-22T10:00:00", "渋谷", "r1", "2026年本部", "K16", 100.0, 250.0,
                                          "26/08/01\t通信費\tA\t\t\t150", 1, "書いた"]


def test_バックアップは指紋だけ残す(tmp_path):
    fake = FakeSheets()
    p = SheetsLedger(fake, "X").backup_pl(b"xlsx", "8月", tmp_path)
    row = fake.tabs["pl_backups"][-1]
    assert row[1:5] == ["8月", "承認前", 4, hashlib.sha256(b"xlsx").hexdigest()]
    assert p.read_bytes() == b"xlsx" and row[5] == str(p)


def test_届かなければSQLite(tmp_path):
    led = get_ledger(None, tmp_path / "l.sqlite")
    assert isinstance(led, Ledger) and led.label == "このPCのみ"
    led = get_ledger({"type": "service_account"}, tmp_path / "l2.sqlite")  # 壊れた鍵
    assert isinstance(led, Ledger) and "届かない" in led.fallback_reason
