"""
本部経費ハブの画面（要件定義 §5）。app.py のフォーマット選択から呼ばれる。
  ① 取込（Amex CSV × PL）→ ② ダッシュボード → ③ 明細一覧 → ④ 確認（要確認だけ）
  → ⑤ 承認前バックアップ → ⑥ PL反映候補（CSV）
PLへの書き込みはしない（Phase 1）。差異は人が確認するまで確定しない。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from .ledger import Ledger
from .models import PlMatch, Status
from .pipeline import EXPORT_COLS, allocation_text, pl_sheets, run, summarize, to_csv
from .pl_notes import DEFAULT_SHEET
from .pl_source import Grid, grids_from_sheets, grids_from_xlsx

MONTHS = [f"{m}月" for m in range(1, 13)]
ACTIONS = ("承認", "修正", "保留", "除外")
DEPARTMENTS = ("本部", "桜木町", "新子安", "白根", "さいわい")
LEDGER_PATH = Path(os.environ.get("EXPENSE_HUB_DIR", Path.home() / ".john_expense_hub")) / "ledger.sqlite"


_REPO_SECRETS = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"


def _sa_info() -> dict | None:
    try:
        info = st.secrets.get("gcp_service_account")
    except Exception:  # secrets.toml が無い環境
        info = None
    if not info and _REPO_SECRETS.exists():
        # ローカルで別フォルダから起動したとき（Streamlit は起動フォルダの .streamlit しか見ない）
        import tomllib

        info = tomllib.loads(_REPO_SECRETS.read_text(encoding="utf-8")).get("gcp_service_account")
    return dict(info) if info else None


@st.cache_resource
def _ledger() -> Ledger:
    return Ledger(LEDGER_PATH)


@st.cache_data(ttl=300, show_spinner="収支計画スプシ（本部＋4店舗タブ）を読んでいます…")
def _grids_from_sheets(sheets: tuple[str, ...]) -> dict[str, Grid]:
    return grids_from_sheets(_sa_info(), list(sheets))


def _load_pl(sheet: str) -> dict[str, Grid] | None:
    """本部タブ＋店舗収支タブを読む（店舗タブは按分照合に使う）。"""
    sa = _sa_info()
    if sa:
        c1, c2 = st.columns([3, 1])
        c1.success(f"収支計画スプシに直結中（読み取り専用）｜タブ「{sheet}」", icon="🔗")
        if c2.button("最新を読み直す", width="stretch"):
            _grids_from_sheets.clear()
            st.session_state.pop("hub_key", None)
        try:
            grids = _grids_from_sheets(tuple(pl_sheets(sheet)))
            if sheet not in grids:
                st.error(f"タブ「{sheet}」が見つかりません")
                return None
            return grids
        except Exception as e:  # 共有漏れ・タブ名違いなど
            st.error(f"スプシを読めませんでした：{e}\n\nサービスアカウントのメールがスプシに共有されているか確認してください。")
            return None
    st.info(
        "スプシ直結はまだ設定されていません（Streamlit の secrets に gcp_service_account が無い）。"
        "設定が済むまでは、スプシを「ファイル→ダウンロード→xlsx」して下に置いてください。",
        icon="ℹ️",
    )
    up = st.file_uploader("収支計画スプシ（xlsx）", type=["xlsx"], key="hub_pl_xlsx")
    if up is None:
        return None
    grids = grids_from_xlsx(up.getvalue(), pl_sheets(sheet))
    if sheet not in grids:
        st.error(f"xlsxにタブ「{sheet}」がありません")
        return None
    return grids


def _dec() -> dict:
    return st.session_state.setdefault("hub_decisions", {})


def _effective_status(r) -> str:
    d = _dec().get(r.id)
    if d:
        return {"承認": "APPROVED", "修正": "APPROVED", "保留": "REVIEW_REQUIRED", "除外": "EXCLUDED"}[d["action"]]
    return r.approval_status.value


def render() -> None:
    st.subheader("本部経費ハブ — 原本 × PLセルメモ照合（Phase 1：アメックス）")
    st.caption("原本取込 → 自動整形 → 重複検出 → PLセルメモ照合 → 差異確認 → 承認 → バックアップ → PL反映候補")

    c1, c2, c3 = st.columns([2, 1, 2])
    c1.selectbox("対象法人", ["株式会社ジョン"], key="hub_corp")
    default_m = MONTHS[(datetime.now().month - 2) % 12]
    month = c2.selectbox("対象月（PLの月列）", MONTHS, index=MONTHS.index(default_m), key="hub_month")
    sheet = c3.text_input("PLのタブ", DEFAULT_SHEET, key="hub_sheet")

    grids = _load_pl(sheet)
    src = st.file_uploader("① 原本：アメックス ご利用明細CSV（activity.csv）", type=["csv"], key="hub_src")
    if grids is None or src is None:
        st.stop()
    grid = grids[sheet]
    missing = [t for t in pl_sheets(sheet) if t not in grids]
    if missing:
        st.caption("店舗タブが見つからず按分照合を省いたもの：" + "、".join(missing))

    ledger = _ledger()
    key = (src.name, len(src.getvalue()), month, sheet, grid.origin)
    if st.session_state.get("hub_key") != key:
        try:
            res = run(src.getvalue(), src.name, grids, month, sheet, ledger=ledger)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        st.session_state.hub_key = key
        st.session_state.hub_res = res
        st.session_state.hub_decisions = {}
    res = st.session_state.hub_res

    if res.duplicate_of:
        st.warning(
            f"この原本は取込済みです（{res.duplicate_of['filename']}／{res.duplicate_of['imported_at']}）。"
            "照合結果は表示しますが、台帳には二重登録していません。",
            icon="⚠️",
        )

    _dashboard(res)
    _table(res)
    _review(res, grid, month, ledger)
    _post_candidates(res, grid, month, ledger)


def _dashboard(res) -> None:
    s = summarize(res.records)
    st.markdown("#### ② ダッシュボード")
    eff = [_effective_status(r) for r in res.records]
    pending = sum(1 for r, e in zip(res.records, eff) if e == "REVIEW_REQUIRED")
    approved = sum(1 for e in eff if e == "APPROVED")
    m = st.columns(5)
    m[0].metric("入力ソース：アメックス", f"{s['行数']}行")
    m[1].metric("経費総額", f"{s['経費総額']:,}円", f"除外 {s['除外額（口座振替等）']:,}円", delta_color="off")
    m[2].metric("自動確認済み", f"{s['自動確認済み']}件", f"うち按分一致 {s['按分一致']}件", delta_color="off")
    m[3].metric("要確認（残り）", f"{pending}件")
    m[4].metric("差異額", f"{s['差異額']:,}円")
    m = st.columns(5)
    m[0].metric("PL未反映候補", f"{s['PL未反映']}件")
    m[1].metric("計上月差", f"{s['計上月差']}件")
    m[2].metric("二重計上候補", "再取込" if res.duplicate_of else "0件")
    m[3].metric("PL反映待ち（承認済み）", f"{approved}件")
    m[4].metric("証憑", "Phase 2", help="領収書・請求書の紐付けは Phase 2")
    bad = [t for t in res.cell_totals if t["diff"]]
    if bad:
        st.warning(
            "PLのセル値とメモ明細の合計が合わないセル："
            + "、".join(f"{t['cell']}（{t['row_label']}）差 {t['diff']:,.0f}円" for t in bad)
        )


def _table(res) -> None:
    st.markdown("#### ③ 明細一覧")
    rows = []
    for r in sorted(res.records, key=lambda x: (x.transaction_date, x.source_row_number)):
        d = r.to_row()
        row = {j: d[k] for k, j in EXPORT_COLS}
        row["ステータス"] = _effective_status(r)
        row["按分"] = allocation_text(r)
        dec = _dec().get(r.id)
        if dec:
            row["確認者"] = dec["reviewer"]
            if dec.get("category"):
                row["科目"] = dec["category"]
        rows.append(row)
    df = pd.DataFrame(rows)
    only = st.toggle("要確認だけ表示", value=False, key="hub_only_review")
    if only:
        df = df[df["ステータス"] == "REVIEW_REQUIRED"]
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button(
        "処理結果をCSVでダウンロード",
        to_csv(res.records),
        file_name=f"本部経費_照合結果_{st.session_state.hub_month}.csv",
        mime="text/csv",
    )


def _review(res, grid: Grid, month: str, ledger: Ledger) -> None:
    targets = [r for r in res.records if r.approval_status == Status.REVIEW_REQUIRED]
    st.markdown(f"#### ④ 確認（要確認 {len(targets)}件）")
    if not targets:
        st.success("要確認はありません。")
        return
    reviewer = st.text_input("確認者", value=st.session_state.get("hub_reviewer", "渋谷"), key="hub_reviewer")
    labels = sorted({str(v).strip() for (r, c), (v, _) in grid.cells.items() if c == 2 and r > 3 and v})
    for r in targets:
        with st.container(border=True):
            left, mid, right = st.columns([1, 1.2, 1.4])
            with left:
                st.markdown("**原本**")
                st.write(f"{r.transaction_date}｜{r.vendor_raw.strip()}")
                st.write(f"**{r.amount:,}円**（{r.source_file_id} 行{r.source_row_number}）")
            with mid:
                st.markdown("**判定**")
                st.write(f"{r.pl_note_match_status.value}：{r.judgement_reason}")
                if r.pl_note_match_status == PlMatch.AMOUNT_DIFF:
                    st.caption("承認＝原本の金額が正しい（PLを原本に合わせる候補を作る）")
            with right:
                st.markdown(f"**PLセルメモ {r.pl_cell or '（該当なし）'}**")
                if r.pl_cell:
                    rr, cc = _rc(r.pl_cell)
                    st.code(grid.note(rr, cc) or "（メモなし）", language=None)
            a1, a2, a3 = st.columns([2, 2, 3])
            cur = _dec().get(r.id, {})
            action = a1.radio("判断", ACTIONS, horizontal=True, key=f"act_{r.id}",
                              index=ACTIONS.index(cur["action"]) if cur else 2)
            cat = a2.selectbox("科目（修正時）", [r.expense_category] + [l for l in labels if l != r.expense_category],
                               key=f"cat_{r.id}")
            dept = a3.selectbox("部門", DEPARTMENTS, key=f"dept_{r.id}")
            if st.button("この判断を記録", key=f"save_{r.id}"):
                _dec()[r.id] = {"action": action, "category": cat if action == "修正" else "", "dept": dept,
                               "reviewer": reviewer, "at": datetime.now().isoformat(timespec="seconds")}
                r.reviewer = reviewer
                r.reviewed_at = datetime.now()
                r.department = dept
                if action == "修正":
                    r.expense_category = cat
                r.log(f"REVIEW:{action}", f"科目={r.expense_category} 部門={dept}", actor=reviewer)
                ledger.update(r, month)
                st.rerun()


def _rc(coord: str) -> tuple[int, int]:
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

    col, row = coordinate_from_string(coord)
    return row, column_index_from_string(col)


def _post_candidates(res, grid: Grid, month: str, ledger: Ledger) -> None:
    st.markdown("#### ⑤ 承認前バックアップ → ⑥ PL反映候補")
    approved = [r for r in res.records if _dec().get(r.id, {}).get("action") in ("承認", "修正")]
    if not approved:
        st.caption("要確認を「承認」または「修正」にすると、ここにPL反映候補が出ます。")
        return
    bk = st.session_state.get("hub_backup")
    if not bk:
        if st.button("PLのバックアップを作成（反映候補を出す前に必須）", type="primary"):
            data = grid.to_xlsx()
            p = ledger.backup_pl(data, month, LEDGER_PATH.parent / "backup")
            st.session_state.hub_backup = {"path": str(p), "data": data}
            st.rerun()
        return
    st.success(f"バックアップ作成済み：{Path(bk['path']).name}")
    st.download_button("バックアップ（xlsx）をダウンロード", bk["data"], file_name=Path(bk["path"]).name)

    rows = []
    for r in approved:
        if not r.pl_cell:
            continue
        rr, cc = _rc(r.pl_cell)
        old = grid.value(rr, cc)
        delta = r.amount - (r.pl_amount or 0) if r.pl_note_match_status == PlMatch.AMOUNT_DIFF else r.amount
        new = old + delta if isinstance(old, (int, float)) else None
        line = f"{r.transaction_date:%y/%m/%d}\t{r.expense_category}\t{r.vendor_raw.strip()}\t\t\t{r.amount:,}"
        rows.append({
            "PLセル": r.pl_cell, "科目": r.expense_category, "旧値": old, "増減": delta, "新値": new,
            "メモ差し替え（旧）": f"{r.pl_amount:,}" if r.pl_amount is not None else "",
            "メモ追記（新）": line, "承認者": _dec()[r.id]["reviewer"], "承認日時": _dec()[r.id]["at"],
        })
    if not rows:
        st.info("承認済みの行に反映先のPLセルがありません（PL未反映候補は、科目を決めてから反映先を選ぶ機能を次段で追加）。")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("Phase 1 ではPLへ自動で書き込みません。この表（旧値・新値・メモ）を見て手で反映してください。")
    st.download_button(
        "PL反映候補をCSVでダウンロード",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"PL反映候補_{month}.csv",
        mime="text/csv",
    )
