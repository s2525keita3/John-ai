"""共有: Cursor 向けフィードバック1行CSV（UTF-8 BOM）と Streamlit フォーム。"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


def read_version_line(version_file: Path) -> str:
    try:
        lines = version_file.read_text(encoding="utf-8").strip().splitlines()
        return lines[0] if lines else "?"
    except OSError:
        return "?"


def build_feedback_csv_bytes(
    *,
    app_label: str,
    kind: str,
    summary: str,
    detail: str,
    version: str,
) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["アプリ", "種別", "概要", "詳細", "アプリ版", "記入日時(ISO)"])
    w.writerow(
        [
            app_label,
            kind,
            summary or "",
            detail or "",
            version,
            datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        ]
    )
    return buf.getvalue().encode("utf-8-sig")


def render_feedback_form(
    *,
    app_label: str,
    version_file: Path,
    form_key: str,
) -> None:
    """改善・連絡用フォーム。集計CSVの右列やサイドバーに配置可能。"""
    version = read_version_line(version_file)
    st.caption("改善・連絡用（1行CSV。Cursor に貼って依頼できます）")
    with st.form(f"fb_{form_key}"):
        fb_kind = st.selectbox(
            "種別",
            [
                "エラー",
                "スタッフ追加",
                "項目追加",
                "追加指示・要望",
                "その他",
            ],
            index=0,
        )
        fb_summary = st.text_input("概要（一行）", placeholder="例: 振分がおかしい")
        fb_detail = st.text_area(
            "詳細",
            height=100,
            placeholder="再現手順・追加したい項目・指示内容など",
        )
        fb_submitted = st.form_submit_button("フィードバックCSVを表示・ダウンロード")
    if fb_submitted:
        fb_csv = build_feedback_csv_bytes(
            app_label=app_label,
            kind=fb_kind,
            summary=fb_summary,
            detail=fb_detail,
            version=version,
        )
        st.download_button(
            "↓ フィードバックCSVを保存",
            data=fb_csv,
            file_name=f"feedback_{form_key}.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"fb_dl_{form_key}",
        )
        st.code(fb_csv.decode("utf-8-sig"), language=None)
