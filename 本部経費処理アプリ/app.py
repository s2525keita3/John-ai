"""
本部経費処理 — 月次の振り分け・分類（MVP）
要件: 本部経費処理 自動化 要件定義書 v2 のステップ2〜4 を簡易実装
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
from csv_loader import is_probably_pdf_bytes, read_csv_auto
from pl_accounts import pl_dropdown_options
from aozora_filters import filter_aozora_hq_noise
from enex_fleet_master import (
    apply_enex_default_card_mapping,
    merge_enex_extract_with_master,
    staff_name_to_initials_display,
    summarize_enex_by_base,
    summarize_enex_by_staff,
)
from enex_fleet_pdf import (
    filter_amex_hq_noise,
    filter_exclude_orico,
    parse_enex_fleet_pdf_bytes,
)
from payroll_hq import (
    DEFAULT_NAME_ROW,
    RESULT_LABEL,
    aggregate_hq_personnel_cost,
    load_payroll_matrix,
)
from yokohama_excel import read_yokohama_bank_excel
from yokohama_hq_rules import apply_yokohama_hq_master_rules
from yokohama_scan_pdf import extract_yokohama_scan_pdf, scan_df_to_bank_work

_ROOT = Path(__file__).resolve().parent

# 本部経費の計上・入力用スプレッドシート
HONBU_KEIHI_SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1rPs01xlB1Iv8a8ovRH8eSIDJGvqCa1mn5SLM2SwL71A/"
    "edit?gid=1846887392#gid=1846887392"
)

# 支給控除一覧：氏名行の列見出しに含まれるキーワードで本部対象列を特定
HQ_PERSONNEL_KEYWORDS = ("本部", "桜木町", "新子安", "白根", "さいわい")


def _combine_yokohama_summary(df: pd.DataFrame) -> pd.Series:
    """科目・支払先・摘要を結合し、キーワード照合に使う（いずれか欠けても可）。"""
    cols = [c for c in ("科目", "支払先", "摘要") if c in df.columns]
    if not cols:
        return pd.Series([""] * len(df), index=df.index)
    acc = df[cols[0]].fillna("").astype(str).str.strip()
    for c in cols[1:]:
        acc = acc + " " + df[c].fillna("").astype(str).str.strip()
    return acc.str.replace(r"\s+", " ", regex=True).str.strip()


# 結果テーブル（画面）では出さない列（CSVダウンロードには残す）
_RESULT_TABLE_OMIT_COLS = (
    "残高",
    "データソース区分",
    "海外通貨利用金額",
    "換算レート",
    "メモ",
)

# エネフリ（通常表示）：カードマスタ紐づけ列は振分PLの次に並べる
_ENEX_DISPLAY_COLS_ORDER = ("カード番号", "拠点", "車両番号", "スタッフ名")
# エネフリ（コンパクト表示）：車両番号は出さない
_ENEX_COMPACT_ORDER = ("拠点", "カード番号", "スタッフ名")

# 横浜信金（CSV／Excel／スキャン）の全明細表示では隠す（ダウンロード「全明細」には残す）
_YOKOHAMA_DISPLAY_EXTRA_OMIT = (
    "計",
    "取込対象外",
    "取込対象外理由",
    "本部調整メモ",
    "出金額_通帳",
    "科目",
)


def _result_table_for_display(
    df: pd.DataFrame,
    *,
    extra_omit_cols: tuple[str, ...] = (),
    enex_compact: bool = False,
) -> pd.DataFrame:
    """画面上の表用: 上記列を隠し、振分PL項目を日付の次に並べる（CSV用の元データは変えない）。"""
    out = df.copy()
    if enex_compact and "スタッフ名" in out.columns:
        out["スタッフ名"] = out["スタッフ名"].map(staff_name_to_initials_display)
    omit = _RESULT_TABLE_OMIT_COLS + extra_omit_cols
    if enex_compact:
        omit = omit + ("振分PL項目", "摘要", "入金額", "車両番号")
    drop_cols = [c for c in omit if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)
    cols = list(out.columns)
    if enex_compact and "日付" in cols:
        enex_first = [c for c in _ENEX_COMPACT_ORDER if c in cols]
        rest = [c for c in cols if c not in ("日付", *enex_first)]
        out = out[["日付"] + enex_first + rest]
    elif "振分PL項目" in cols:
        enex_first = [c for c in _ENEX_DISPLAY_COLS_ORDER if c in cols]
        if "日付" in cols:
            rest = [c for c in cols if c not in ("日付", "振分PL項目", *enex_first)]
            out = out[["日付", "振分PL項目"] + enex_first + rest]
        else:
            rest = [c for c in cols if c not in ("振分PL項目", *enex_first)]
            out = out[["振分PL項目"] + enex_first + rest]
    return out


def _result_table_column_config(
    df: pd.DataFrame, *, enex_compact: bool = False
) -> dict:
    """日付を狭く、振分PLは左寄せで見やすく。"""
    cfg: dict = {}
    if "日付" in df.columns:
        cfg["日付"] = st.column_config.TextColumn("日付", width="small")
    if not enex_compact and "振分PL項目" in df.columns:
        cfg["振分PL項目"] = st.column_config.TextColumn("振分PL項目", width="medium")
    if "カード番号" in df.columns:
        cfg["カード番号"] = st.column_config.TextColumn("カード番号", width="small")
    if "拠点" in df.columns:
        cfg["拠点"] = st.column_config.TextColumn("拠点", width="small")
    if "車両番号" in df.columns:
        cfg["車両番号"] = st.column_config.TextColumn("車両番号", width="medium")
    if "スタッフ名" in df.columns:
        label = "スタッフ（イニシャル）" if enex_compact else "スタッフ名"
        w = "small" if enex_compact else "medium"
        cfg["スタッフ名"] = st.column_config.TextColumn(label, width=w)
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
            "カード番号",
            "拠点",
            "車両番号",
            "スタッフ名",
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


st.set_page_config(page_title="本部経費処理（MVP）", layout="wide")
st.title("本部経費処理 — 月次振り分け（MVP）")
st.caption(
    "取引CSVをアップロードし、マスタ（摘要キーワード→自社PL）で自動振り分けします。"
    " 確定／要確認／判断不能の3区分（要件定義書 v2 ステップ4）"
)

with st.container(border=True):
    st.markdown("##### 本部経費のスプレッドシート（入力・計上先）")
    st.caption("振分結果を反映したり、本部経費をまとめるときは、まずここを開いてください。")
    st.link_button(
        "Google スプレッドシートを開く",
        HONBU_KEIHI_SPREADSHEET_URL,
        use_container_width=True,
        type="primary",
    )

if "master_work" not in st.session_state:
    st.session_state.master_work = pd.read_csv(_ROOT / "sample_master.csv", encoding="utf-8-sig")

enex_master_df: pd.DataFrame | None = None
with st.sidebar:
    st.subheader("取引CSVの列名")
    yokohama_ocr_include_review = False
    format_preset = st.selectbox(
        "フォーマット",
        [
            "あおぞらネット銀行（法人口座・標準CSV）",
            "アメックス（activity CSV）",
            "横浜信用金庫（入出金明細・CSV／Excel）",
            "横浜信用金庫（通帳スキャンPDF・OCR）",
            "エネクスフリート（請求書PDF・本部カード0001〜0004）",
            "手動で列名を指定",
        ],
        help="銀行・カードのダウンロードCSVは Shift-JIS（cp932）のことが多いです（自動で utf-8/cp932 を試行）。",
        key="format_preset",
    )
    if format_preset == "あおぞらネット銀行（法人口座・標準CSV）":
        st.info("列名は **日付・摘要・入金金額・出金金額・残高・メモ**（あおぞら標準）で読みます。")
        date_col = "日付"
        summary_col = "摘要"
        in_col = "入金金額"
        out_col = "出金金額"
    elif format_preset == "アメックス（activity CSV）":
        st.info(
            "列は **ご利用日・データ処理日・ご利用内容・金額**（公式 activity 明細）です。"
            " **金額**はカンマ付きのため自動で数値化し、マイナス（振替等）は集計から除外します。"
        )
        date_col = "ご利用日"
        summary_col = "ご利用内容"
        in_col = ""
        out_col = ""
    elif format_preset == "横浜信用金庫（入出金明細・CSV／Excel）":
        st.info(
            "**CSV** または **Excel（.xlsx）** に対応。"
            " Excel は先頭に表題行があっても、**日付・入金・出金** が並ぶ行をヘッダとして自動検出します。"
            " 列は **日付・科目・支払先・摘要・入金・出金・計**（入出金明細）を想定。"
            " **本部マスタ**（店舗計上の除外・中退共6万・日新火災6千固定）を自動適用し、除外行は **取込対象外** とします。"
        )
        date_col = "日付"
        summary_col = "摘要"
        in_col = "入金"
        out_col = "出金"
    elif format_preset == "横浜信用金庫（通帳スキャンPDF・OCR）":
        st.warning(
            "**本番の取込は「横浜信用金庫（入出金明細・CSV／Excel）」を最優先してください。**"
            " 通帳スキャンは罫線・活字・かすれで **OCRが大きく外れる**ことがあり、"
            " 手元通帳と一致しない結果は仕様上よく起こります。"
            " スキャンはあくまで補助として割り切り、**CSVまたは手入力**で確定するのが確実です。"
        )
        st.info(
            "**スキャンPDF**は **EasyOCR を先に試行**（`pip install easyocr`）し、"
            " ダメなときだけ Tesseract にフォールバックします。"
            " 日付・金額が読めない行は **不明／要確認**、既定は **確定** 行のみ振分です。"
            " 本部マスタ（除外・固定額）は、読めた行に適用されます。"
        )
        yokohama_ocr_include_review = st.checkbox(
            "OCRで「要確認」と判定された行も振り分けに含める",
            value=False,
            key="yokohama_ocr_include_review",
        )
        date_col = ""
        summary_col = ""
        in_col = ""
        out_col = ""
    elif format_preset == "エネクスフリート（請求書PDF・本部カード0001〜0004）":
        st.info(
            "**エネクスフリート（エネオス）**の請求書PDFをアップロード。"
            " **（車番　計）** 行の金額を **PDFに出てくるカード番号すべて** で読みます。"
            " **PyMuPDF** が必要です（`pip install pymupdf`）。"
        )
        st.caption(
            "**拠点**はPDFのカード番号から自動で付きます。"
            " **カードマスタCSV（任意）**で **車両番号・スタッフ名**（必要なら拠点の修正）を上書きできます。"
            " 列: **カード番号, 拠点, 車両番号, スタッフ名**（番号は1や01でも可）。"
        )
        enex_master_up = st.file_uploader(
            "エネフリ・カードマスタCSV（任意）",
            type=["csv"],
            key="enex_card_master_upload",
        )
        if enex_master_up is not None:
            try:
                raw_m = enex_master_up.read()
                if is_probably_pdf_bytes(raw_m):
                    st.error(
                        "カードマスタ（任意）の欄に **PDF** が入っています。"
                        " ここは **CSV のみ** です。請求書PDFは **タブ①の取引データ** にアップロードしてください。"
                    )
                else:
                    enex_master_df = read_csv_auto(raw_m)
            except Exception as e:
                st.error(f"カードマスタの読み込みに失敗しました: {e}")
        _dl_enex_master = _ROOT / "default_enex_fleet_card_master.csv"
        if _dl_enex_master.exists():
            st.download_button(
                "カードマスタCSV（同梱・全拠点）",
                data=_dl_enex_master.read_bytes(),
                file_name="default_enex_fleet_card_master.csv",
                key="dl_sample_enex_master",
            )
        else:
            st.download_button(
                "サンプル・カードマスタCSV",
                data=(_ROOT / "sample_enex_fleet_card_master.csv").read_bytes(),
                file_name="sample_enex_fleet_card_master.csv",
                key="dl_sample_enex_master",
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

    with st.expander("詳細設定（データソース・除外ルール）", expanded=False):
        st.caption("通常はこのままで問題ありません。変更するときだけ開いてください。")
        source_col = st.text_input("データソース列（任意）", value="データソース区分")
        use_source = st.checkbox("マスタのデータソース区分で絞り込む", value=False)
        add_src_auto = st.checkbox(
            "プリセットに応じてデータソース区分を自動付与（列が無いとき：あおぞら／アメックス／横浜信金／エネフリ）",
            value=True,
        )
        exclude_orico = st.checkbox(
            "摘要に「オリコ」を含む行を除外（オリコカード明細を振分対象から外す）",
            value=True,
        )
        exclude_amex_hq_noise = st.checkbox(
            "アメックス本部向け: 前回口座振替・ソフトバンク全社一括（約17〜21万）を除外",
            value=True,
            help="前回分口座振替金額は振分対象外。ソフトバンクＭの全社一括は各店按分済みのため除外。",
        )
        exclude_aozora_hq_noise = st.checkbox(
            "あおぞら本部向け: 資金移動・役員振込・支給控除済み・PE納付・社会保険料を除外",
            value=True,
            help="カ）ジヨン系振替、横浜信金への資金移動、三菱UFJ・シブヤケイタ、楽天・石田、PE納付、社会保険料（半角表記含む）。",
        )

    st.divider()
    st.subheader("② マスタ（ドロップダウン）")
    full_pl = st.checkbox(
        "自社PLは「全項目」をドロップダウンに表示",
        value=True,
        key="master_full_pl",
    )
    pl_opts = pl_dropdown_options(full_list=full_pl)

    st.caption(
        "**➕ 行を追加** または表の **+** で行を追加。**行番号**を指定して **削除** もできます。"
        " キーワード・PL・金額レンジは表で編集（上から優先・長いキーワード優先）。"
        " 支給控除の人件費合計は **タブ②（支給控除）** の項目名と対応させています。"
    )
    up_master = st.file_uploader("マスタをCSVで上書き読込（任意）", type=["csv"], key="up_master")
    if up_master is not None:
        try:
            raw = up_master.read()
            st.session_state.master_work = read_csv_auto(raw)
            st.success("マスタを読み込みました")
        except Exception as e:
            st.error(f"読み込み失敗: {e}")

    mw = st.session_state.master_work
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
                st.session_state.master_work = pd.DataFrame(columns=base_cols)
                mw = st.session_state.master_work
            new_row = {c: ("（未選択）" if c == "自社PL勘定項目" else ("" if c in ("摘要キーワード", "データソース区分") else None)) for c in mw.columns}
            st.session_state.master_work = pd.concat(
                [st.session_state.master_work, pd.DataFrame([new_row])],
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
            st.session_state.master_work = st.session_state.master_work.drop(index=idx).reset_index(drop=True)
            st.rerun()

    edited = st.data_editor(
        st.session_state.master_work,
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
    st.session_state.master_work = edited

    sample_bytes = (_ROOT / "sample_master.csv").read_bytes()
    st.download_button("サンプルマスタ（CSV）をダウンロード", data=sample_bytes, file_name="sample_master.csv")

tab1, tab2 = st.tabs(
    ["① 読み込み・振り分け結果", "② 支給控除読み込み"]
)

with tab1:
    st.markdown("### 読み込み（取引データ）")
    st.info(
        "**あおぞら**／**アメックス**はCSV、**横浜信金**は **CSV または xlsx**、**横浜信金（スキャン）**／**エネフリ**は**PDF**。"
        " 左のフォーマットを選んでからアップロードしてください。"
    )
    tx_file = st.file_uploader(
        "取引データ（CSV／Excel／PDF）",
        type=["csv", "pdf", "xlsx", "xlsm"],
        key="tx",
    )
    st.divider()
    run_keihi = st.button("振り分けを実行", type="primary", key="run_keihi")

    if run_keihi:
        if tx_file is None:
            st.error("取引ファイル（CSV または PDF）をアップロードしてください（タブ①）。")
            st.stop()

        raw = tx_file.getvalue()
        name = getattr(tx_file, "name", "") or ""

        if format_preset == "エネクスフリート（請求書PDF・本部カード0001〜0004）":
            if not name.lower().endswith(".pdf"):
                st.error("このプリセットは **PDF** を選んでください（エネクスフリート請求書）。")
                st.stop()
            try:
                work = parse_enex_fleet_pdf_bytes(raw, filename=name)
                work = apply_enex_default_card_mapping(work)
                _def_enex_master = _ROOT / "default_enex_fleet_card_master.csv"
                if _def_enex_master.exists():
                    try:
                        work = merge_enex_extract_with_master(
                            work, read_csv_auto(_def_enex_master.read_bytes())
                        )
                    except Exception as e:
                        st.warning(
                            "同梱のカードマスタ（default_enex_fleet_card_master.csv）の読み込みに失敗しました: "
                            f"{e}"
                        )
                if enex_master_df is not None and not enex_master_df.empty:
                    work = merge_enex_extract_with_master(work, enex_master_df)
            except Exception as e:
                st.error(f"PDFの読み込みに失敗しました: {e}")
                st.stop()
            if work.empty:
                st.error(
                    "対象カードの **（車番　計）** が1件も取れませんでした。"
                    " PDFのテキスト・カードマスタの番号（4桁）を確認するか、別版PDFで試してください。"
                )
                st.stop()
            total_enex = float(pd.to_numeric(work["出金額"], errors="coerce").fillna(0).sum())
            _metric_help = "PDFの「（車番　計）」行の金額のみ。拠点はカード番号から自動付与。"
            st.metric(
                "エネフリ請求書・カード別（車番計）の合計",
                f"{total_enex:,.0f} 円",
                help=_metric_help,
            )
            st.caption(f"抽出: **{len(work)}** 行（カードあたり最大1件・車番計ベース）")
            if "拠点" in work.columns:
                sb = summarize_enex_by_base(work)
                ss = summarize_enex_by_staff(work)
                if not sb.empty:
                    st.subheader("エネフリ：拠点別（車番計）")
                    st.dataframe(sb, width="stretch", hide_index=True)
                if not ss.empty and (
                    "スタッフ名" in work.columns
                    and work["スタッフ名"].fillna("").astype(str).str.strip().ne("").any()
                ):
                    st.subheader("エネフリ：スタッフ別（車番計）")
                    st.dataframe(ss, width="stretch", hide_index=True)
            tx_df = None
        elif format_preset == "横浜信用金庫（通帳スキャンPDF・OCR）":
            if not name.lower().endswith(".pdf"):
                st.error("このプリセットは **PDF** を選んでください（横浜信金の通帳スキャン）。")
                st.stop()
            try:
                scan_df, ocr_msgs = extract_yokohama_scan_pdf(raw, filename=name)
            except Exception as e:
                st.error(f"スキャンPDFの処理に失敗しました: {e}")
                st.stop()
            for m in ocr_msgs:
                st.warning(m)
            if scan_df.empty:
                st.error("OCR結果が空です。EasyOCR の導入（`pip install easyocr`）を確認してください。")
                st.stop()
            st.subheader("横浜信金 OCR 結果（全行・ステータス付き）")
            st.dataframe(scan_df, use_container_width=True, hide_index=True)
            inc = (
                frozenset({"確定", "要確認"})
                if yokohama_ocr_include_review
                else frozenset({"確定"})
            )
            work, excluded_rows, wmsgs = scan_df_to_bank_work(scan_df, include_statuses=inc)
            for m in wmsgs:
                st.warning(m)
            if not excluded_rows.empty:
                st.subheader("振り分け対象外（不明・要確認・または除外）")
                st.caption("誤取り込みを防ぐため、ここに出た行は既定では振り分けに含めません。CSVで修正するか、要確認を含める設定を検討してください。")
                st.dataframe(excluded_rows, use_container_width=True, hide_index=True)
            if work.empty:
                st.error(
                    "振り分けに使える行がありません。「要確認を含める」をオンにするか、"
                    " スキャン品質・OCRエンジンを見直し、またはCSVで手入力してください。"
                )
                st.stop()
            dt = work["日付"].astype(str).str.strip()
            work = work[dt.ne("") & dt.ne("nan") & work["日付"].notna()]
            tx_df = None
        else:
            try:
                if format_preset == "横浜信用金庫（入出金明細・CSV／Excel）" and name.lower().endswith(
                    (".xlsx", ".xlsm")
                ):
                    tx_df = read_yokohama_bank_excel(raw)
                else:
                    if is_probably_pdf_bytes(raw):
                        st.error(
                            "アップロードされたのは **PDF** です。エネクスフリートの請求書のときは、"
                            "左のフォーマットで **エネクスフリート（請求書PDF・本部カード0001〜0004）** "
                            "を選んでから、もう一度「振り分けを実行」してください。"
                        )
                        st.stop()
                    tx_df = read_csv_auto(raw)
            except Exception as e:
                st.error(f"ファイルの読み込みに失敗しました: {e}")
                st.stop()

        if format_preset == "アメックス（activity CSV）":
            need_cols = ("ご利用日", "ご利用内容", "金額")
            for c in need_cols:
                if c not in tx_df.columns:
                    st.error(f"列「{c}」がありません。現在の列: {list(tx_df.columns)}")
                    st.stop()
            work = tx_df.copy()
            work = work.rename(columns={"ご利用日": "日付", "ご利用内容": "摘要"})
            amt = work["金額"].map(parse_amount_cell)
            work["出金額"] = amt.fillna(0).clip(lower=0)
            work = work.drop(columns=["金額"], errors="ignore")
        elif format_preset == "横浜信用金庫（入出金明細・CSV／Excel）":
            need_cols = ("日付", "入金", "出金")
            for c in need_cols:
                if c not in tx_df.columns:
                    st.error(f"列「{c}」がありません。現在の列: {list(tx_df.columns)}")
                    st.stop()
            if "摘要" not in tx_df.columns:
                st.error("列「摘要」がありません（科目・支払先のみの場合は手動プリセットで列名を調整してください）。")
                st.stop()
            work = tx_df.copy()
            work["入金額"] = work["入金"].map(parse_amount_cell).fillna(0)
            work["出金額"] = work["出金"].map(parse_amount_cell).fillna(0)
            work = work.drop(columns=["入金", "出金"], errors="ignore")
            work["摘要"] = _combine_yokohama_summary(work)
            dt = work["日付"].astype(str).str.strip()
            work = work[dt.ne("") & dt.ne("nan") & work["日付"].notna()]
        elif format_preset == "エネクスフリート（請求書PDF・本部カード0001〜0004）":
            pass  # work は上で構築済み
        elif format_preset == "横浜信用金庫（通帳スキャンPDF・OCR）":
            pass  # work は上で構築済み
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

        if exclude_amex_hq_noise:
            work = filter_amex_hq_noise(work, summary_col="摘要", out_col="出金額")

        if exclude_aozora_hq_noise and format_preset == "あおぞらネット銀行（法人口座・標準CSV）":
            work = filter_aozora_hq_noise(work, summary_col="摘要")

        if add_src_auto and source_col not in work.columns:
            if format_preset == "あおぞらネット銀行（法人口座・標準CSV）":
                work[source_col] = "あおぞら"
            elif format_preset == "アメックス（activity CSV）":
                work[source_col] = "アメックス"
            elif format_preset in (
                "横浜信用金庫（入出金明細・CSV／Excel）",
                "横浜信用金庫（通帳スキャンPDF・OCR）",
            ):
                work[source_col] = "横浜信金"
            elif format_preset == "エネクスフリート（請求書PDF・本部カード0001〜0004）":
                work[source_col] = "エネクスフリート"

        if format_preset in (
            "横浜信用金庫（入出金明細・CSV／Excel）",
            "横浜信用金庫（通帳スキャンPDF・OCR）",
        ):
            work = apply_yokohama_hq_master_rules(work)

        master_rows = load_master_dataframe(st.session_state.master_work)
        if not master_rows:
            st.error("マスタに有効な行がありません（摘要キーワードと自社PLを両方指定）。")
            st.stop()

        scol = source_col if use_source and source_col in work.columns else None

        if format_preset in (
            "横浜信用金庫（入出金明細・CSV／Excel）",
            "横浜信用金庫（通帳スキャンPDF・OCR）",
        ) and "取込対象外" in work.columns:
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

        _yokohama_presets = (
            "横浜信用金庫（入出金明細・CSV／Excel）",
            "横浜信用金庫（通帳スキャンPDF・OCR）",
        )
        _table_extra_omit = (
            _YOKOHAMA_DISPLAY_EXTRA_OMIT if format_preset in _yokohama_presets else ()
        )

        st.subheader("全明細（振分結果付き）")
        _enex_ui = (
            format_preset == "エネクスフリート（請求書PDF・本部カード0001〜0004）"
        )
        if _enex_ui and "カード番号" in result.columns:
            st.caption(
                "エネフリ明細：**カード番号**は請求書から。**拠点・スタッフ（フルネーム）**は"
                " 同梱マスタまたは任意アップロードのCSVで紐づけ。"
                " この表では **振分PL・摘要・入金・車両番号は非表示**、スタッフは **イニシャル**。"
                " 番号がルール外のときは拠点が「（拠点要確認）」になります。"
            )
        display_all = _result_table_for_display(
            result, extra_omit_cols=_table_extra_omit, enex_compact=_enex_ui
        )
        st.dataframe(
            display_all,
            column_config=_result_table_column_config(display_all, enex_compact=_enex_ui),
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
            review_base = _result_table_for_display(
                review_base, extra_omit_cols=_table_extra_omit, enex_compact=_enex_ui
            )
            review_base = _sanitize_dataframe_for_streamlit_data_editor(review_base)
            col_cfg = _result_table_column_config(review_base, enex_compact=_enex_ui)
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
    "- Googleスプレッドシート連携・画像OCR・学習用マスタ更新は未実装のMVPです（横浜信金は**CSV入出金明細**プリセットで対応）。\n"
    "- マスタ初版は、提供待ちデータ（MF仕訳・PL実績）到着後に精緻化できます。"
)
