"""
処理済み経費台帳（SQLite）。同一原本の再取込拒否・監査ログ・PLバックアップの置き場。
削除はしない（論理削除＝EXCLUDED）。
"""
from __future__ import annotations

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
