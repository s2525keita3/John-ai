"""
処理済み経費台帳。同一原本の再取込拒否・監査ログ・PLバックアップの置き場。
削除はしない（論理削除＝EXCLUDED）。
  Ledger       … SQLite（このPCのみ。Streamlit Cloud では再起動で消える）
  SheetsLedger … 台帳スプシ（再起動しても消えない）。get_ledger() がどちらかを選ぶ
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import ExpenseRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_batches (
  file_hash TEXT PRIMARY KEY,
  source_type TEXT, filename TEXT, rows INTEGER, imported_at TEXT
);
CREATE TABLE IF NOT EXISTS records (
  id TEXT PRIMARY KEY,
  file_hash TEXT, row_number INTEGER, month TEXT,
  status TEXT, pl_match TEXT, data TEXT, updated_at TEXT,
  UNIQUE(file_hash, row_number)
);
CREATE TABLE IF NOT EXISTS audit_log (
  at TEXT, actor TEXT, record_id TEXT, action TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS pl_backups (
  at TEXT, month TEXT, path TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS pl_writes (
  at TEXT, actor TEXT, record_id TEXT, sheet TEXT, cell TEXT,
  old_value REAL, new_value REAL, note_line TEXT, ok INTEGER, message TEXT
);
"""


class DuplicateImport(Exception):
    pass


class Ledger:
    label = "このPCのみ"
    fallback_reason = ""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Streamlit は再実行ごとに別スレッドになるので、スレッド縛りを外して排他は lock で取る
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def already_imported(self, file_hash: str) -> dict | None:
        cur = self.db.execute("SELECT filename, imported_at FROM import_batches WHERE file_hash=?", (file_hash,))
        r = cur.fetchone()
        return {"filename": r[0], "imported_at": r[1]} if r else None

    def save_import(self, source_type: str, filename: str, file_hash: str, month: str, records: list[ExpenseRecord]) -> None:
        prev = self.already_imported(file_hash)
        if prev:
            raise DuplicateImport(f"同じ原本は取込済み（{prev['filename']}／{prev['imported_at']}）。二重計上を防ぐため再取込しません")
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO import_batches VALUES (?,?,?,?,?)", (file_hash, source_type, filename, len(records), now)
            )
            for r in records:
                self._upsert(r, month, now)

    def _upsert(self, r: ExpenseRecord, month: str, now: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?)",
            (
                r.id, r.source_file_hash, r.source_row_number, month,
                r.approval_status.value, r.pl_note_match_status.value,
                json.dumps(r.to_row(), ensure_ascii=False, default=str), now,
            ),
        )
        for e in r.audit_log:
            self.db.execute(
                "INSERT INTO audit_log VALUES (?,?,?,?,?)", (e["at"], e["actor"], r.id, e["action"], e["detail"])
            )
        r.audit_log.clear()  # 書き出し済みのログは台帳側が正本

    def update(self, r: ExpenseRecord, month: str) -> None:
        with self.lock, self.db:
            self._upsert(r, month, datetime.now().isoformat(timespec="seconds"))

    def backup_pl(self, xlsx_bytes: bytes, month: str, backup_dir: str | Path, reason: str = "承認前") -> Path:
        d = Path(backup_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = d / f"PL_backup_{month}_{stamp}.xlsx"
        p.write_bytes(xlsx_bytes)
        with self.lock, self.db:
            self.db.execute("INSERT INTO pl_backups VALUES (?,?,?,?)", (stamp, month, str(p), reason))
        return p

    def log_write(self, actor: str, result) -> None:
        """PLへの書き込み1件（要件定義 §12-6：反映セル・旧値・新値・担当者・日時）。"""
        c = result.change
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO pl_writes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (result.at, actor, c.record_id, c.sheet, c.cell, c.old_value, c.new_value, c.note_line,
                 int(result.ok), result.message),
            )


# ---- 台帳スプシ（Streamlit Cloud 用） ----------------------------------------

LEDGER_SPREADSHEET_ID = "1kTGjE4JUuOLpXMbdao0muECSb0D7vo9bPel9lhxhkSo"
SCOPES_RW = ["https://www.googleapis.com/auth/spreadsheets"]

# 1テーブル＝1タブ。列順は SQLite と同じ（pl_backups だけ xlsx 本体を置けないので中身の指紋を持つ）
SHEET_COLUMNS = {
    "import_batches": ["file_hash", "source_type", "filename", "rows", "imported_at"],
    "records": ["id", "file_hash", "row_number", "month", "status", "pl_match", "data", "updated_at"],
    "audit_log": ["at", "actor", "record_id", "action", "detail"],
    "pl_backups": ["at", "month", "reason", "bytes", "sha256", "local_path"],
    "pl_writes": ["at", "actor", "record_id", "sheet", "cell", "old_value", "new_value", "note_line", "ok", "message"],
}


class SheetsLedger:
    """台帳スプシ版。公開の口は Ledger と同じ。
    すべて追記のみ（values.append）。records は更新のたびに1行足す＝同じ id は一番下の行が最新。
    pl_backups は xlsx 本体を置けない（サービスアカウントに Drive 容量が無い）ので、
    日時・月・理由・バイト数・sha256 だけ残し、本体はローカル保存（できれば）＋画面のダウンロードで持つ。
    """

    label = "スプシ（再起動しても消えない）"

    def __init__(self, service, spreadsheet_id: str = LEDGER_SPREADSHEET_ID):
        self.svc = service
        self.sid = spreadsheet_id
        self.lock = threading.Lock()
        self._ensure_tabs()  # ここで届かなければ例外＝get_ledger が SQLite に切り替える

    def _ensure_tabs(self) -> None:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.sid, fields="sheets.properties.title").execute()
        have = {s["properties"]["title"] for s in meta.get("sheets", [])}
        add = [{"addSheet": {"properties": {"title": t}}} for t in SHEET_COLUMNS if t not in have]
        if add:
            self.svc.spreadsheets().batchUpdate(spreadsheetId=self.sid, body={"requests": add}).execute()
        got = self.svc.spreadsheets().values().batchGet(
            spreadsheetId=self.sid, ranges=[f"{t}!1:1" for t in SHEET_COLUMNS]
        ).execute()
        heads = [vr.get("values") for vr in got.get("valueRanges", [])]
        data = [{"range": f"{t}!A1", "values": [cols]} for (t, cols), h in zip(SHEET_COLUMNS.items(), heads) if not h]
        if data:
            self.svc.spreadsheets().values().batchUpdate(
                spreadsheetId=self.sid, body={"valueInputOption": "RAW", "data": data}
            ).execute()

    def _append(self, table: str, rows: list[list]) -> None:
        if not rows:
            return
        # RAW＝「=」で始まる摘要も数式にしない
        self.svc.spreadsheets().values().append(
            spreadsheetId=self.sid, range=f"{table}!A1", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS", body={"values": [["" if v is None else v for v in r] for r in rows]},
        ).execute()

    def already_imported(self, file_hash: str) -> dict | None:
        got = self.svc.spreadsheets().values().get(spreadsheetId=self.sid, range="import_batches!A2:E").execute()
        for row in got.get("values", []):
            if row and row[0] == file_hash:
                row = row + [""] * (5 - len(row))
                return {"filename": row[2], "imported_at": row[4]}
        return None

    def save_import(self, source_type: str, filename: str, file_hash: str, month: str, records: list[ExpenseRecord]) -> None:
        with self.lock:
            prev = self.already_imported(file_hash)
            if prev:
                raise DuplicateImport(f"同じ原本は取込済み（{prev['filename']}／{prev['imported_at']}）。二重計上を防ぐため再取込しません")
            now = datetime.now().isoformat(timespec="seconds")
            # 明細を先に書き、取込記録（二重取込の鍵）は最後に書く。途中で落ちたら鍵が無いので
            # もう一度取り込める。明細は id で引く追記型なので、やり直しで二重に数えることはない
            self._upsert(records, month, now)
            self._append("import_batches", [[file_hash, source_type, filename, len(records), now]])

    def _upsert(self, records: list[ExpenseRecord], month: str, now: str) -> None:
        recs, logs = [], []
        for r in records:
            recs.append([
                r.id, r.source_file_hash, r.source_row_number, month,
                r.approval_status.value, r.pl_note_match_status.value,
                json.dumps(r.to_row(), ensure_ascii=False, default=str), now,
            ])
            logs += [[e["at"], e["actor"], r.id, e["action"], e["detail"]] for e in r.audit_log]
        self._append("records", recs)
        self._append("audit_log", logs)
        for r in records:
            r.audit_log.clear()  # 書き出し済みのログは台帳側が正本

    def update(self, r: ExpenseRecord, month: str) -> None:
        with self.lock:
            self._upsert([r], month, datetime.now().isoformat(timespec="seconds"))

    def backup_pl(self, xlsx_bytes: bytes, month: str, backup_dir: str | Path, reason: str = "承認前") -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = Path(backup_dir) / f"PL_backup_{month}_{stamp}.xlsx"
        saved = ""
        try:  # ローカル保存はできれば（Cloud では再起動で消える。本体は画面のダウンロードで持つ）
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(xlsx_bytes)
            saved = str(p)
        except OSError:
            pass
        with self.lock:
            self._append("pl_backups", [[stamp, month, reason, len(xlsx_bytes), hashlib.sha256(xlsx_bytes).hexdigest(), saved]])
        return p

    def log_write(self, actor: str, result) -> None:
        """PLへの書き込み1件（要件定義 §12-6：反映セル・旧値・新値・担当者・日時）。"""
        c = result.change
        with self.lock:
            self._append("pl_writes", [[result.at, actor, c.record_id, c.sheet, c.cell, c.old_value, c.new_value,
                                        c.note_line, int(result.ok), result.message]])


def _sheets_service(sa_info: dict):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES_RW)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def get_ledger(sa_info: dict | None, local_path: str | Path, spreadsheet_id: str | None = None):
    """secrets があって台帳スプシに届けば SheetsLedger、だめなら SQLite の Ledger。
    切り替えた理由は ledger.fallback_reason に残す（画面に出す用）。"""
    reason = "サービスアカウント未設定"
    if sa_info:
        try:
            return SheetsLedger(_sheets_service(sa_info), spreadsheet_id or LEDGER_SPREADSHEET_ID)
        except Exception as e:  # 共有漏れ・API無効・通信断
            reason = f"台帳スプシに届かない：{e}"
    led = Ledger(local_path)
    led.fallback_reason = reason
    return led
