"""
本部経費ハブの画面（要件定義 §5）。app.py のフォーマット選択から呼ばれる。
  ① 取込（Amex CSV × PL）→ ② ダッシュボード → ③ 明細一覧 → ④ 確認（要確認だけ）
  → ⑤ 承認前バックアップ → ⑥ PLへ反映（承認した行だけ・pl_writer）
  別タブ：PL点検（pl_check・反映前チェック）
差異は人が確認するまで確定しない。書き込みは承認済みの行だけ（バックアップ・確認チェック後）。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from .learning import apply_learned, decision_row, learn
from .ledger import LEDGER_SPREADSHEET_ID, Ledger, get_ledger
from .models import PlMatch, Status
from .pipeline import EXPORT_COLS, allocation_text, pl_sheets, run, summarize, to_csv
from .pl_check import check_pl, latest_month
from .pl_notes import DEFAULT_SHEET, month_columns
from .pl_source import Grid, grids_from_sheets, grids_from_xlsx
from .pl_writer import apply_changes, plan_changes

MONTHS = [f"{m}月" for m in range(1, 13)]
ACTIONS = ("承認", "修正", "保留", "除外")
DEPARTMENTS = ("本部", "桜木町", "新子安", "白根", "さいわい")
LEDGER_PATH = Path(os.environ.get("EXPENSE_HUB_DIR", Path.home() / ".john_expense_hub")) / "ledger.sqlite"


_REPO_SECRETS = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"


def _secret(key: str):
    try:
        v = st.secrets.get(key)
    except Exception:  # secrets.toml が無い環境
        v = None
    if not v and _REPO_SECRETS.exists():
        # ローカルで別フォルダから起動したとき（Streamlit は起動フォルダの .streamlit しか見ない）
        import tomllib

        v = tomllib.loads(_REPO_SECRETS.read_text(encoding="utf-8")).get(key)
    return v


def _sa_info() -> dict | None:
    info = _secret("gcp_service_account")
    return dict(info) if info else None


@st.cache_resource(show_spinner="台帳を開いています…")
def _ledger() -> Ledger:
    """secrets があれば台帳スプシ（再起動しても消えない）、無ければこのPCの SQLite。"""
    return get_ledger(_sa_info(), LEDGER_PATH, _secret("ledger_spreadsheet_id") or LEDGER_SPREADSHEET_ID)


@st.cache_data(ttl=300, show_spinner="収支計画スプシ（本部＋4店舗タブ）を読んでいます…")
def _grids_from_sheets(sheets: tuple[str, ...]) -> dict[str, Grid]:
    return grids_from_sheets(_sa_info(), list(sheets))


def _load_pl(sheet: str) -> dict[str, Grid] | None:
    """本部タブ＋店舗収支タブを読む（店舗タブは按分照合に使う）。"""
    sa = _sa_info()
    if sa:
        c1, c2 = st.columns([3, 1])
        c1.success(f"収支計画スプシに直結中｜タブ「{sheet}」（読むのは読み取り専用。書くのは⑥で承認した行だけ）", icon="🔗")
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
    st.subheader("本部経費ハブ")
    st.caption("原本取込 → 自動整形 → 重複検出 → PLセルメモ照合 → 差異確認 → 承認 → バックアップ → PL反映｜手順の正本＝ルールブック §10")

    c1, c2, c3 = st.columns([2, 1, 2])
    c1.selectbox("対象法人", ["株式会社ジョン"], key="hub_corp")
    default_m = MONTHS[(datetime.now().month - 2) % 12]
    month = c2.selectbox("対象月（PLの月列）", MONTHS, index=MONTHS.index(default_m), key="hub_month")
    sheet = c3.text_input("PLのタブ", DEFAULT_SHEET, key="hub_sheet")

    grids = _load_pl(sheet)
    if grids is None:
        return
    t1, t2 = st.tabs(["① アメックス照合", "② PL点検（反映前チェック）"])
    with t1:
        _render_amex(grids, month, sheet)
    with t2:
        _render_check(grids, month)


CHECK_MEANING = {
    "A セル＝メモ合計": "セルの金額とメモの合計が合わない → メモを直す",
    "B メモの形": "金額のない行・残高列が残った行 → アプリの出力を貼り直す",
    "C 付け替え": "付け替え5点の抜け → 本部管理費明細を確認",
    "D 本部分だけ": "本部タブに請求の総額（店舗分を含む）",
    "E 按分": "本部経費の按分率と人数が合わない",
    "F 本部経費の参照": "店舗の本部経費が本部タブを参照していない",
}


def _render_check(grids: dict[str, Grid], month: str) -> None:
    st.markdown("収支計画スプシの **本部＋4店舗** を読み、ルールブック §10 ⑤ の反映前チェックをまとめて行います（読むだけ・書き込みません）。")
    latest = latest_month(grids)
    if latest and latest != month:
        st.caption(f"按分（行名の人数・率）の点検は最新月（{latest}）だけで行います。")
    findings = check_pl(grids, month)
    must = [f for f in findings if f.level == "要対応"]
    m = st.columns(3)
    m[0].metric("要対応", f"{len(must)}件")
    m[1].metric("注意", f"{len(findings) - len(must)}件")
    m[2].metric("点検した月", month)
    if not findings:
        st.success("すべて○です。⑥ 3シート転記に進めます。")
        return
    df = pd.DataFrame([
        {"区分": f.level, "点検": f.check, "意味": CHECK_MEANING.get(f.check, ""), "部門": f.dept, "セル": f.cell, "内容": f.detail}
        for f in findings
    ])
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("点検結果をCSVでダウンロード", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"PL点検_{month}.csv", mime="text/csv")


def _render_amex(grids: dict[str, Grid], month: str, sheet: str) -> None:
    src = st.file_uploader("原本：アメックス ご利用明細CSV（activity.csv）", type=["csv"], key="hub_src")
    if src is None:
        return
    grid = grids[sheet]
    missing = [t for t in pl_sheets(sheet) if t not in grids]
    if missing:
        st.caption("店舗タブが見つからず按分照合を省いたもの：" + "、".join(missing))

    ledger = _ledger()
    st.caption(f"台帳：{ledger.label}" + (f"（{ledger.fallback_reason}）" if getattr(ledger, "fallback_reason", "") else ""))
    key = (src.name, len(src.getvalue()), month, sheet, grid.origin)
    if st.session_state.get("hub_key") != key:
        try:
            res = run(src.getvalue(), src.name, grids, month, sheet, ledger=ledger)
            # 過去の判断を当てる（同じ利用先で同じ判断が2回続いたものは自動確定）
            try:
                learned_n = apply_learned(res.records, learn(ledger.decisions()))
            except Exception as e:  # 台帳が読めなくても照合は続ける
                learned_n = 0
                st.caption(f"学習済み判断を読めませんでした：{e}")
            res.summary["学習で自動確定"] = learned_n
        except ValueError as e:
            st.error(str(e))
            return
        st.session_state.hub_key = key
        st.session_state.hub_res = res
        st.session_state.hub_decisions = {}
        for k in ("hub_backup", "hub_write_results", "hub_targets"):
            st.session_state.pop(k, None)
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
    m[2].metric("自動確認済み", f"{s['自動確認済み']}件",
                f"按分一致 {s['按分一致']}／学習 {res.summary.get('学習で自動確定', 0)}", delta_color="off")
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
                ledger.save_decision(decision_row(r, _dec()[r.id], month))
                st.rerun()


def _rc(coord: str) -> tuple[int, int]:
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

    col, row = coordinate_from_string(coord)
    return row, column_index_from_string(col)


def _post_candidates(res, grid: Grid, month: str, ledger: Ledger) -> None:
    st.markdown("#### ⑤ 承認前バックアップ → ⑥ PLへ反映")
    approved = [r for r in res.records if _dec().get(r.id, {}).get("action") in ("承認", "修正")]
    if not approved:
        st.caption("要確認を「承認」または「修正」にすると、ここにPL反映の案が出ます。")
        return

    # PL未反映の行は、入れる行（科目）を人が選ぶ
    targets = st.session_state.setdefault("hub_targets", {})
    hq_col = month_columns(grid).get(month)
    rows_by_label = {str(grid.value(r, 2)).strip(): r for r in range(4, 26) if grid.value(r, 2)}
    for r in approved:
        if r.pl_note_match_status == PlMatch.NOT_IN_PL and hq_col:
            label = st.selectbox(
                f"反映先の行：{r.transaction_date}｜{r.vendor_raw.strip()[:24]}｜{r.amount:,}円",
                ["（選ぶ）"] + list(rows_by_label), key=f"tgt_{r.id}",
            )
            if label == "（選ぶ）":
                targets.pop(r.id, None)
            else:
                targets[r.id] = Grid.coord(rows_by_label[label], hq_col)
                r.expense_category = label

    changes = plan_changes(approved, _dec(), grid, targets)
    if not changes:
        st.info("書き込む対象がありません（計上月差は数字を動かさない／PL未反映は反映先の行を選ぶ）。")
        return
    df = pd.DataFrame([{
        "PLセル": c.cell, "旧値": c.old_value, "増減": c.delta, "新値": c.new_value,
        "メモに追記する行": c.note_line.replace("\t", "｜"), "理由": c.reason, "書けない理由": c.blocked,
    } for c in changes])
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("反映案をCSVでダウンロード", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"PL反映案_{month}.csv", mime="text/csv")

    bk = st.session_state.get("hub_backup")
    if not bk:
        if st.button("PLのバックアップを作成（書き込みの前に必須）", type="primary"):
            data = grid.to_xlsx()
            p = ledger.backup_pl(data, month, LEDGER_PATH.parent / "backup")
            st.session_state.hub_backup = {"path": str(p), "data": data}
            st.rerun()
        return
    st.success(f"バックアップ作成済み：{Path(bk['path']).name}")
    st.download_button("バックアップ（xlsx）をダウンロード", bk["data"], file_name=Path(bk["path"]).name)

    done = st.session_state.get("hub_write_results")
    if done:
        st.markdown("**書き込み結果**")
        st.dataframe(pd.DataFrame(done), hide_index=True, width="stretch")
        st.caption("書いた内容は台帳（pl_writes）に、セル・旧値・新値・担当者・日時つきで残しています。")
        return

    sa = _sa_info()
    if not sa or grid.origin != "sheets":
        st.caption("PLへの書き込みはスプシ直結のときだけ使えます（xlsx読み込みのときは反映案CSVを見て手で反映）。")
        return
    ok = st.checkbox("旧値・新値・追記するメモを確認した（書くのは上の表の行だけ。既存のメモは消さない）", key="hub_confirm")
    if st.button("PLに反映する", type="primary", disabled=not ok):
        actor = st.session_state.get("hub_reviewer", "")
        results = apply_changes(sa, changes)
        for x in results:
            ledger.log_write(actor, x)
        st.session_state.hub_write_results = [
            {"PLセル": x.change.cell, "結果": "OK" if x.ok else "書かなかった", "内容": x.message, "読み直した値": x.after_value}
            for x in results
        ]
        _grids_from_sheets.clear()
        st.rerun()
