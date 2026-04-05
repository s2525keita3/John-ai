"""
halka_AI — 本部経費処理（**本部経費処理アプリ／JOHN とは独立したパッケージ**）

- 取込: あおぞらCSV、マネフォカード利用明細CSV（公式列／旧activity互換）、手動列名
- 横浜信用金庫・エネクスフリートは経費計算に使用しない
- 既定マスタ: 同梱の halka_master.csv（左サイドバー②で編集・CSV上書き可）
- 摘要に APｱﾌﾟﾗｽ 等が含まれる行は出金額を50%按分（リース料・複合機按分）

起動: リポジトリルートで `streamlit run halka_ai/app.py` または `streamlit run halka_ai_app.py`
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from classifier import (
    aggregate_by_pl,
    classify_dataframe,
    load_master_dataframe,
    parse_amount_cell,
)
from csv_loader import read_csv_auto
from pl_accounts import pl_dropdown_options
from aozora_filters import filter_aozora_hq_noise
from filters import filter_exclude_orico
from payroll_hq import (
    DEFAULT_NAME_ROW,
    RESULT_LABEL,
    aggregate_hq_personnel_cost,
    load_payroll_matrix,
)

_ROOT = Path(__file__).resolve().parent
_HALKA_MASTER_CSV = _ROOT / "halka_master.csv"

# halka 向け入力・計上用スプレッドシート
HALKA_SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1sfPRvU5ueLXdne-S3abXs2Iszndr-y5y96eA2w6l4O8/"
    "edit?gid=880856182#gid=880856182"
)

# マネフォクラウド「カード利用明細」CSV（公式列 or 旧アメックス activity 互換）
_PRESET_MF_CARD = "マネフォカード（利用明細CSV）"

# 摘要に含まれたら出金額を 50% する（複合機リース等の按分）
_HALF_AMOUNT_SUMMARY_MARKERS: tuple[str, ...] = (
    "APｱﾌﾟﾗｽ",
    "APアプラス",
)

# 支給控除一覧：氏名行の列見出しに含まれるキーワードで本部対象列を特定
HQ_PERSONNEL_KEYWORDS = ("本部", "桜木町", "新子安", "白根", "さいわい")


def _normalize_halka_master_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """空欄だらけの列が float 推論され data_editor と衝突するのを防ぐ。"""
    out = df.copy()
    for col in ("摘要キーワード", "自社PL勘定項目", "データソース区分"):
        if col in out.columns:
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else str(x))
    for col in ("金額下限", "金額上限"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _moneyforward_card_df_to_work(df: pd.DataFrame) -> pd.DataFrame:
    """
    マネフォ「カード利用明細」公式CSV → 日付・摘要・出金額。
    摘要は 支払先（英字等）と 支払先（漢字）を結合（マスタのキーワード照合用）。
    """
    work = df.copy()
    pay = (
        work["支払先"].fillna("")
        if "支払先" in work.columns
        else pd.Series("", index=work.index)
    )
    pay = pay.astype(str).str.strip()
    kanji = (
        work["支払先（漢字）"].fillna("")
        if "支払先（漢字）" in work.columns
        else pd.Series("", index=work.index)
    )
    kanji = kanji.astype(str).str.strip()
    combined = (pay + " " + kanji).str.replace(r"\s+", " ", regex=True).str.strip()
    work["摘要"] = combined
    dt = pd.to_datetime(work["取引日時"], errors="coerce")
    work["日付"] = dt.dt.strftime("%Y%m%d")
    work.loc[dt.isna(), "日付"] = ""
    amt = pd.to_numeric(work["金額"], errors="coerce").fillna(0.0)
    work["出金額"] = amt.abs()
    return work


def _apply_halka_ap_plus_half(work: pd.DataFrame) -> pd.DataFrame:
    """APアプラス（半角表記含む）の摘要は出金を50%にし、按分メモを付与。"""
    if work.empty or "摘要" not in work.columns or "出金額" not in work.columns:
        return work
    w = work.copy()
    s = w["摘要"].fillna("").astype(str)
    mask = s.map(lambda t: any(m in t for m in _HALF_AMOUNT_SUMMARY_MARKERS))
    if not mask.any():
        return w
    amt = pd.to_numeric(w["出金額"], errors="coerce").fillna(0.0)
    w.loc[mask, "出金額"] = (amt[mask] * 0.5).round(0)
    if "按分メモ" not in w.columns:
        w["按分メモ"] = ""
    w.loc[mask, "按分メモ"] = "APアプラス50%按分（複合機等）"
    return w


# 結果テーブル（画面）では出さない列（CSVダウンロードには残す）
_RESULT_TABLE_OMIT_COLS = (
    "残高",
    "データソース区分",
    "海外通貨利用金額",
    "換算レート",
    "メモ",
)


def _result_table_for_display(
    df: pd.DataFrame,
    *,
    extra_omit_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """画面上の表用: 上記列を隠し、振分PL項目を日付の次に並べる（CSV用の元データは変えない）。"""
    out = df.copy()
    omit = _RESULT_TABLE_OMIT_COLS + extra_omit_cols
    drop_cols = [c for c in omit if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)
    cols = list(out.columns)
    if "振分PL項目" in cols:
        if "日付" in cols:
            rest = [c for c in cols if c not in ("日付", "振分PL項目")]
            out = out[["日付", "振分PL項目"] + rest]
        else:
            rest = [c for c in cols if c != "振分PL項目"]
            out = out[["振分PL項目"] + rest]
    return out


def _result_table_column_config(df: pd.DataFrame) -> dict:
    """日付を狭く、振分PLは左寄せで見やすく。"""
    cfg: dict = {}
    if "日付" in df.columns:
        cfg["日付"] = st.column_config.TextColumn("日付", width="small")
    if "振分PL項目" in df.columns:
        cfg["振分PL項目"] = st.column_config.TextColumn("振分PL項目", width="medium")
    return cfg


def _sanitize_dataframe_for_streamlit_data_editor(df: pd.DataFrame) -> pd.DataFrame:
    """
    st.data_editor + TextColumn と pandas の dtype が一致しないと Streamlit が落ちるため、
    文字列系・日付を str 化し、数値・真偽はそのままにする。
    """
    out = df.copy()
    force_str = frozenset(
        {
            "日付",
            "振分PL項目",
            "判断理由",
            "今後の仕分けメモ",
            "摘要",
            "メモ",
            "ご利用内容",
        }
    )
    for c in out.columns:
        s = out[c]
        if c in force_str:
            if pd.api.types.is_datetime64_any_dtype(s):
                out[c] = pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
            else:
                out[c] = s.map(lambda x: "" if pd.isna(x) else str(x))
            continue
        if pd.api.types.is_bool_dtype(s):
            continue
        if pd.api.types.is_numeric_dtype(s):
            continue
        if pd.api.types.is_datetime64_any_dtype(s):
            out[c] = pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        else:
            out[c] = s.map(lambda x: "" if pd.isna(x) else str(x))
    return out


# 本部人件費テーブル（画面）では内訳の社保4列を出さない（CSVには残す）
_PAYROLL_DISPLAY_OMIT_COLS = (
    "健康保険料(会社)",
    "介護保険料(会社)",
    "厚生年金保険料(会社)",
    "子ども・子育て拠出金(会社)",
)


def _payroll_table_for_display(df: pd.DataFrame) -> pd.DataFrame:
    keep = [c for c in df.columns if c not in _PAYROLL_DISPLAY_OMIT_COLS]
    return df[keep].copy()


def _dataframe_pl_classified_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    振分PLが付き、マスタ除外・取込対象外でない行（「分類できた」明細のみ）。
    """
    if df.empty or "振分PL項目" not in df.columns:
        return pd.DataFrame()
    sub = df.copy()
    pl = sub["振分PL項目"].fillna("").astype(str).str.strip()
    mask = pl.ne("") & ~pl.isin(("（未選択）", "—", "-"))
    if "分類結果" in sub.columns:
        mask &= ~sub["分類結果"].astype(str).eq("除外")
    if "取込対象外" in sub.columns:
        mask &= ~sub["取込対象外"].fillna(False).astype(bool)
    return sub.loc[mask].copy()


def _pl_classified_csv_bytes(df: pd.DataFrame) -> bytes:
    """PL分類済みCSV用: 取込対象外・調整用の列は含めない。"""
    out = df.copy()
    drop_pl_csv = (
        "取込対象外",
        "取込対象外理由",
        "本部調整メモ",
        "出金額_通帳",
        "計",
        "科目",
    )
    drop_cols = [c for c in drop_pl_csv if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)
    return out.to_csv(index=False).encode("utf-8-sig")


st.set_page_config(page_title="halka_AI — 本部経費処理", layout="wide")
st.title("halka_AI — 本部経費処理（月次振り分け）")
st.caption(
    "取引CSVをアップロードし、マスタ（摘要キーワード→自社PL）で自動振り分けします。"
    " 確定／要確認／判断不能の3区分（要件定義書 v2 ステップ4）。"
    " **halka_AI** はあおぞら・マネフォカード利用明細・手動列名。既定マスタは **halka_master.csv** です。"
)

with st.container(border=True):
    st.markdown("##### halka 用スプレッドシート（入力・計上先）")
    st.caption("振分結果を反映したり、本部経費をまとめるときは、まずここを開いてください。")
    st.link_button(
        "Google スプレッドシートを開く",
        HALKA_SPREADSHEET_URL,
        use_container_width=True,
        type="primary",
    )

# ディスク上の halka_master.csv が更新されたら再読込（session_state が古いマスタのまま残るのを防ぐ）
_halka_master_mtime = _HALKA_MASTER_CSV.stat().st_mtime if _HALKA_MASTER_CSV.is_file() else 0.0
if (
    "halka_master_loaded_mtime" not in st.session_state
    or st.session_state.halka_master_loaded_mtime != _halka_master_mtime
):
    st.session_state.halka_master_work = _normalize_halka_master_dataframe(
        pd.read_csv(_HALKA_MASTER_CSV, encoding="utf-8-sig")
    )
    st.session_state.halka_master_loaded_mtime = _halka_master_mtime

with st.sidebar:
    st.subheader("取引CSVの列名")
    format_preset = st.selectbox(
        "フォーマット",
        [
            "あおぞらネット銀行（法人口座・標準CSV）",
            _PRESET_MF_CARD,
            "手動で列名を指定",
        ],
        help="銀行・カードのダウンロードCSVは Shift-JIS（cp932）のことが多いです（自動で utf-8/cp932 を試行）。",
        key="format_preset",
    )
    if format_preset == "あおぞらネット銀行（法人口座・標準CSV）":
        st.info(
            "列名は **日付・摘要・入金金額・出金金額・残高・メモ**（あおぞら標準）で読みます。"
        )
        date_col = "日付"
        summary_col = "摘要"
        in_col = "入金金額"
        out_col = "出金金額"
    elif format_preset == _PRESET_MF_CARD:
        st.info(
            "**公式（推奨）:** マネフォ管理サイトの **カード利用明細** CSV。"
            " **取引日時・支払先・支払先（漢字）・金額** など（ファイル名例: カード利用明細_*.csv）。"
            " 金額はマイナスなので **絶対値** を出金として扱います。"
            " **カード名義人** 列があれば結果に残ります（利用者の目安）。"
            " **互換:** 旧 **ご利用日・ご利用内容・金額** のCSVも同じプリセットで読み込めます。"
        )
        date_col = ""
        summary_col = ""
        in_col = ""
        out_col = ""
    else:
        date_col = st.text_input("日付の列名", value="日付")
        summary_col = st.text_input("摘要の列名", value="摘要")
        in_col = st.text_input("入金額の列名", value="入金額")
        out_col = st.text_input("出金額の列名", value="出金額")

    # 詳細設定（データソース・除外ルール）は非表示。既定は従来の expander 既定値と同じ。
    source_col = "データソース区分"
    use_source = False
    add_src_auto = True
    exclude_orico = True
    exclude_aozora_hq_noise = True

    st.divider()
    st.subheader("② マスタ（ドロップダウン）")
    full_pl = st.checkbox(
        "自社PLは「全項目」をドロップダウンに表示",
        value=True,
        key="master_full_pl",
    )
    pl_opts = pl_dropdown_options(full_list=full_pl)

    st.session_state.halka_master_work = _normalize_halka_master_dataframe(
        st.session_state.halka_master_work
    )
    up_master = st.file_uploader("マスタをCSVで上書き読込（任意）", type=["csv"], key="up_master")
    if up_master is not None:
        try:
            raw = up_master.read()
            st.session_state.halka_master_work = _normalize_halka_master_dataframe(read_csv_auto(raw))
            st.success("マスタを読み込みました")
        except Exception as e:
            st.error(f"読み込み失敗: {e}")

    mw = st.session_state.halka_master_work
    n_master = len(mw)
    ac1, ac2 = st.columns(2)
    with ac1:
        if st.button("➕ 行を追加", type="primary", key="master_add_row"):
            base_cols = list(mw.columns) if not mw.empty else [
                "摘要キーワード",
                "自社PL勘定項目",
                "金額下限",
                "金額上限",
                "データソース区分",
            ]
            if mw.empty:
                st.session_state.halka_master_work = pd.DataFrame(columns=base_cols)
                mw = st.session_state.halka_master_work
            new_row = {c: ("（未選択）" if c == "自社PL勘定項目" else ("" if c in ("摘要キーワード", "データソース区分") else None)) for c in mw.columns}
            st.session_state.halka_master_work = pd.concat(
                [st.session_state.halka_master_work, pd.DataFrame([new_row])],
                ignore_index=True,
            )
            st.rerun()
    with ac2:
        max_row = max(1, n_master)
        del_no = st.number_input(
            "削除行（1始まり）",
            min_value=1,
            max_value=max_row,
            value=min(1, max_row),
            key="master_del_row_no",
            disabled=n_master == 0,
        )
        if st.button("🗑 削除", key="master_del_row_btn", disabled=n_master == 0):
            idx = int(del_no) - 1
            st.session_state.halka_master_work = st.session_state.halka_master_work.drop(index=idx).reset_index(drop=True)
            st.rerun()

    edited = st.data_editor(
        st.session_state.halka_master_work,
        column_config={
            "摘要キーワード": st.column_config.TextColumn("摘要キーワード（部分一致）", width="medium"),
            "自社PL勘定項目": st.column_config.SelectboxColumn(
                "自社PL勘定項目",
                options=pl_opts,
                required=False,
            ),
            "金額下限": st.column_config.NumberColumn("金額下限（空＝無制限）", format="%d"),
            "金額上限": st.column_config.NumberColumn("金額上限（空＝無制限）", format="%d"),
            "データソース区分": st.column_config.TextColumn("データソース（空＝全ソース）", width="small"),
        },
        num_rows="dynamic",
        width="stretch",
        hide_index=False,
        key="master_editor",
    )
    st.session_state.halka_master_work = edited

    master_dl = _HALKA_MASTER_CSV.read_bytes() if _HALKA_MASTER_CSV.is_file() else edited.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "halka 既定マスタ（CSV）をダウンロード",
        data=master_dl,
        file_name="halka_master.csv",
    )

tab1, tab2 = st.tabs(
    ["① 読み込み・振り分け結果", "② 支給控除読み込み"]
)

with tab1:
    st.markdown("### 読み込み（取引データ）")
    st.info(
        "**あおぞら**／**マネフォ・カード利用明細**（**カード利用明細_*.csv**）はCSV。"
        " **手動**は列名を左で指定。あおぞらの日付は **20260204** 形式の行もあります。"
        " 横浜信用金庫・エネクスフリートの取込は行いません。"
    )
    tx_file = st.file_uploader(
        "取引データ（CSV）",
        type=["csv"],
        key="tx",
    )
    st.divider()
    run_keihi = st.button("振り分けを実行", type="primary", key="run_keihi")

    if run_keihi:
        if tx_file is None:
            st.error("取引ファイル（CSV）をアップロードしてください（タブ①）。")
            st.stop()

        raw = tx_file.getvalue()

        try:
            tx_df = read_csv_auto(raw)
        except Exception as e:
            st.error(f"ファイルの読み込みに失敗しました: {e}")
            st.stop()

        if format_preset == _PRESET_MF_CARD:
            if "取引日時" in tx_df.columns and "金額" in tx_df.columns:
                if "支払先" not in tx_df.columns and "支払先（漢字）" not in tx_df.columns:
                    st.error(
                        "マネフォ公式CSVでは **支払先** または **支払先（漢字）** 列が必要です。"
                        f" 現在の列: {list(tx_df.columns)}"
                    )
                    st.stop()
                work = _moneyforward_card_df_to_work(tx_df)
            elif (
                "ご利用日" in tx_df.columns
                and "ご利用内容" in tx_df.columns
                and "金額" in tx_df.columns
            ):
                work = tx_df.copy()
                work = work.rename(columns={"ご利用日": "日付", "ご利用内容": "摘要"})
                amt = work["金額"].map(parse_amount_cell)
                work["出金額"] = amt.fillna(0).clip(lower=0)
                work = work.drop(columns=["金額"], errors="ignore")
            else:
                st.error(
                    "マネフォカード用の列が見つかりません。\n\n"
                    "- **公式:** **取引日時**・**金額**・（**支払先** または **支払先（漢字）**）\n"
                    "- **互換（旧activity）:** **ご利用日**・**ご利用内容**・**金額**\n\n"
                    f"現在の列: {list(tx_df.columns)}"
                )
                st.stop()
        else:
            for need in (summary_col, out_col):
                if need not in tx_df.columns:
                    st.error(f"列「{need}」がありません。現在の列: {list(tx_df.columns)}")
                    st.stop()

            work = tx_df.copy()
            work = work.rename(
                columns={
                    summary_col: "摘要",
                    out_col: "出金額",
                    in_col: "入金額",
                }
            )
            if date_col in work.columns:
                work = work.rename(columns={date_col: "日付"})

        if exclude_orico:
            work = filter_exclude_orico(work, summary_col="摘要")

        if exclude_aozora_hq_noise and format_preset == "あおぞらネット銀行（法人口座・標準CSV）":
            work = filter_aozora_hq_noise(work, summary_col="摘要")

        work = _apply_halka_ap_plus_half(work)

        if add_src_auto and source_col not in work.columns:
            if format_preset == "あおぞらネット銀行（法人口座・標準CSV）":
                work[source_col] = "あおぞら"
            elif format_preset == _PRESET_MF_CARD:
                work[source_col] = "マネフォカード"

        master_rows = load_master_dataframe(st.session_state.halka_master_work)
        if not master_rows:
            st.error("マスタに有効な行がありません（摘要キーワードと自社PLを両方指定）。")
            st.stop()

        scol = source_col if use_source and source_col in work.columns else None

        if "取込対象外" in work.columns:
            ex_mask = work["取込対象外"].fillna(False)
            work_in = work.loc[~ex_mask]
            work_ex = work.loc[ex_mask]
        else:
            work_in = work
            work_ex = pd.DataFrame()

        if work_in.empty and work_ex.empty:
            st.error("取引行がありません。")
            st.stop()

        if not work_in.empty:
            result_in = classify_dataframe(
                work_in, master_rows, summary_col="摘要", source_col=scol
            )
            if "本部調整メモ" in result_in.columns:
                adj = result_in["本部調整メモ"].fillna("").astype(str).str.strip()
                m = adj.ne("")
                result_in.loc[m, "メモ"] = (
                    result_in.loc[m, "メモ"].fillna("").astype(str).str.strip()
                    + " "
                    + adj[m]
                ).str.strip()
            if "按分メモ" in result_in.columns:
                am = result_in["按分メモ"].fillna("").astype(str).str.strip()
                m2 = am.ne("")
                if m2.any():
                    result_in.loc[m2, "メモ"] = (
                        result_in.loc[m2, "メモ"].fillna("").astype(str).str.strip()
                        + " "
                        + am[m2]
                    ).str.strip()
                result_in = result_in.drop(columns=["按分メモ"], errors="ignore")
        else:
            result_in = pd.DataFrame()

        if not work_ex.empty:
            result_ex = work_ex.copy()
            result_ex["分類結果"] = "除外"
            result_ex["振分PL項目"] = ""
            result_ex["メモ"] = result_ex["取込対象外理由"].fillna("")
        else:
            result_ex = pd.DataFrame()

        if result_in.empty:
            result = result_ex
        elif result_ex.empty:
            result = result_in
        else:
            result = pd.concat([result_in, result_ex]).sort_index()

        st.subheader("振り分け結果")
        st.success("処理が完了しました。続きに集計・明細・CSVがあります。")

        c1, c2, c3, c4, c5 = st.columns(5)
        vc = result["分類結果"].value_counts()
        c1.metric("確定", int(vc.get("確定", 0)))
        c2.metric("要確認", int(vc.get("要確認", 0)))
        c3.metric("判断不能", int(vc.get("判断不能", 0)))
        c4.metric("除外", int(vc.get("除外", 0)))
        c5.metric("件数合計", len(result))

        st.subheader("全明細（振分結果付き）")
        display_all = _result_table_for_display(result)
        st.dataframe(
            display_all,
            column_config=_result_table_column_config(display_all),
            width="stretch",
            hide_index=True,
        )

        st.subheader("勘定項目別 合計（出金・入金・簡易）")
        if "振分PL項目" in result.columns and (
            "出金額" in result.columns or "入金額" in result.columns
        ):
            agg = aggregate_by_pl(result)
            if agg.empty:
                st.info("集計できる行がありません。")
            else:
                st.dataframe(agg, use_container_width=True, hide_index=True)
        else:
            st.warning(
                "「振分PL項目」および「出金額」または「入金額」の列が必要です。"
            )

        st.divider()
        st.subheader("要確認・判断不能（レビュー・自由記載）")
        st.caption(
            "**判断不能**の行については、**社長へデータを渡し、マスタへの追加を依頼する旨を報告**してください。"
            " 下の表で **判断理由** と **今後の仕分けメモ** を追記し、"
            " 一番右の **「社長へ渡す…」** からCSVを出力して共有・Cursor でマスタ更新に使えます。"
        )
        review_base = result[result["分類結果"].isin(["要確認", "判断不能"])].copy()
        if review_base.empty:
            st.info("要確認・判断不能の行はありません。")
            edited_review = None
        else:
            if "判断理由" not in review_base.columns:
                review_base["判断理由"] = ""
            if "今後の仕分けメモ" not in review_base.columns:
                review_base["今後の仕分けメモ"] = ""
            review_base = _result_table_for_display(review_base)
            review_base = _sanitize_dataframe_for_streamlit_data_editor(review_base)
            col_cfg = _result_table_column_config(review_base)
            for c in review_base.columns:
                if c in ("判断理由", "今後の仕分けメモ"):
                    col_cfg[c] = st.column_config.TextColumn(
                        c,
                        width="large",
                        help="自由記載（Cursor でマスタ・除外ルールを更新するときのメモ用）",
                    )
            edited_review = st.data_editor(
                review_base,
                column_config=col_cfg,
                width="stretch",
                hide_index=True,
                num_rows="fixed",
                key="review_rows_editor",
            )

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        pl_only_df = _dataframe_pl_classified_rows(result)
        csv_full = result.to_csv(index=False).encode("utf-8-sig")

        dl1, dl2, dl3 = st.columns(3)
        dl1.download_button(
            "全明細をCSVダウンロード",
            data=csv_full,
            file_name=f"本部経費_振分結果_全明細_{stamp}.csv",
        )
        if len(pl_only_df) > 0:
            dl2.download_button(
                "PL分類済みのみCSV",
                data=_pl_classified_csv_bytes(pl_only_df),
                file_name=f"本部経費_PL分類済みのみ_{stamp}.csv",
                help="振分PLが付き、取込対象外・マスタ除外でない行。取込対象外の列は含みません。",
            )
        else:
            dl2.caption("PL分類済みの行がありません。")

        if edited_review is not None and not edited_review.empty:
            rev_bytes = edited_review.to_csv(index=False).encode("utf-8-sig")
            dl3.download_button(
                "社長へ渡す判断不能・要確認ファイル（CSV）",
                data=rev_bytes,
                file_name=f"本部経費_社長向け_要確認判断不能_{stamp}.csv",
                help="要確認・判断不能の行のみ。判断理由・今後の仕分けメモ付き。社長共有・マスタ追記用。",
            )
        else:
            dl3.caption("要確認・判断不能の行があるときに、社長向けCSVをダウンロードできます。")

    else:
        st.info(
            "取引データをアップロードし、左サイドバーの **② マスタ** を確認してから、"
            " 上の **「振り分けを実行」** を押してください。"
        )

with tab2:
    st.markdown("### 支給控除の読み込み・本部人件費")
    st.caption(
        "「支給合計」＋会社負担社保（健康・介護・厚生・子ども・子育て）を **人件費(支給額,健康,介護,厚生,子ども)** に集計します。"
        " **表の1行目** を氏名・列見出し行として参照します（下でキーワードを選択）。"
    )
    payroll_file = st.file_uploader(
        "支給控除一覧表（xlsx または csv）",
        type=["xlsx", "xlsm", "csv"],
        key="payroll",
    )
    hq_selected = st.multiselect(
        "本部の対象キーワード（1行目に含まれる列を集計）",
        options=list(HQ_PERSONNEL_KEYWORDS),
        default=list(HQ_PERSONNEL_KEYWORDS),
        help="【本部】【桜木町】【新子安】【白根】【さいわい】に該当する列をまとめます。不要な店舗は選択を外してください。",
    )
    run_payroll = st.button("本部人件費を集計", type="primary", key="run_payroll")

    if run_payroll:
        if payroll_file is None:
            st.error("ファイルをアップロードしてください。")
        else:
            try:
                raw = payroll_file.getvalue()
                df = load_payroll_matrix(raw)
                surnames = tuple(hq_selected)
                if not surnames:
                    st.error("対象キーワードを1つ以上選択してください。")
                    st.stop()
                res_df, errs = aggregate_hq_personnel_cost(
                    df,
                    name_row=DEFAULT_NAME_ROW,
                    surnames=surnames,
                )
                for e in errs:
                    st.warning(e)
                if res_df.empty:
                    st.error("集計結果がありません。表の形式（1行目に氏名・列見出し）・キーワードの設定を確認してください。")
                else:
                    st.metric(RESULT_LABEL + "（本部合計）", f"{res_df[RESULT_LABEL].iloc[-1]:,.0f} 円")
                    st.dataframe(
                        _payroll_table_for_display(res_df),
                        width="stretch",
                        hide_index=True,
                    )
                    csv_p = res_df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        "集計結果をCSVダウンロード",
                        data=csv_p,
                        file_name="本部人件費_支給控除集計.csv",
                        key="dl_payroll",
                    )
            except Exception as e:
                st.error(f"読み込みまたは集計に失敗しました: {e}")

st.divider()
st.markdown("##### 次の拡張（要件定義書との対応）")
st.markdown(
    "- Googleスプレッドシート連携・画像OCR・学習用マスタ更新は未実装のMVPです。\n"
    "- **halka_AI** はあおぞら／**マネフォ・カード利用明細CSV（公式列）**／手動列名。横浜信金・エネフリの取込は行いません。\n"
    "- マスタは **`halka_master.csv`**（送付いただいた科目・店舗ベースの初版）。**APｱﾌﾟﾗｽ** は摘要一致時に **出金50%按分** します。"
)
