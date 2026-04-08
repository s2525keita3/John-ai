"""
Amazon / アスクル × あおぞら 照合 UI（halka_ai および 本部経費処理アプリ から共有）。
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from amazon_aozora_reconcile import (
    build_amazon_payment_table,
    filter_bank_visa_debit_rows,
    match_amazon_to_bank,
)
from askul_aozora_reconcile import (
    build_askul_payment_table,
    match_askul_to_bank,
)
from csv_loader import read_csv_auto

AMAZON_JP_HOME_URL = "https://www.amazon.co.jp/?ref_=abn_logo"
ASKUL_HOME_URL = "https://www.askul.co.jp/"

# メインの expander 内ファイル欄だけ大きなドロップゾーンにする（サイドバーは対象外）
AMAZON_RECONCILE_DROPZONE_CSS = """
<style>
[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stFileUploaderDropzone"] {
    min-height: 168px !important;
    padding: 1.1rem 1rem !important;
    align-items: center !important;
    justify-content: center !important;
    border: 2px dashed rgba(71, 85, 119, 0.4) !important;
    border-radius: 12px !important;
    background: linear-gradient(165deg, #f8fafc 0%, #eef2f7 100%) !important;
    box-sizing: border-box !important;
    transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stFileUploaderDropzone"]:hover {
    border-color: rgba(37, 99, 235, 0.55) !important;
    background: #f5f9ff !important;
    box-shadow: 0 1px 8px rgba(37, 99, 235, 0.08);
}
[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stFileUploader"] {
    width: 100% !important;
}
[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stFileUploader"] section {
    gap: 0.35rem !important;
}
</style>
"""


def render_amazon_askul_aozora_reconcile_expander(*, key_prefix: str = "") -> None:
    """
    key_prefix: 別アプリに同 UI を埋め込むとき、Streamlit の widget key 衝突を避ける（例: \"honbu_keihi_\"）。
    """
    kp = key_prefix

    with st.expander("Amazon / アスクル × あおぞら 照合（任意）", expanded=True):
        st.caption(
            "**Amazon 法人向け注文履歴**または**アスクル購入履歴**と**あおぞら口座明細**を、"
            "**金額が一致**し、**Amazon の支払い確定日**／**アスクルの受付日**と**口座の日付**が"
            " **±2 日**以内なら同一とみなします。"
            " Amazon の照合金額は **支払い金額**（分割カード決済ごと）。"
            " アスクルは **受付日＋伝票番号** ごとに **税込小計**（値引き行はマイナス）を合算した額です。"
            " **注文の合計（税込）**は注文全体の合計のため、口座の各引落としとは一致しません。"
            " **支払認証ID/請求書番号** があると、同一注文内の複数回引落としを区別できます。"
            " 口座は **出金がある行**のみ対象です。"
        )
        _lnk_amz, _lnk_ask = st.columns(2, gap="small")
        with _lnk_amz:
            st.link_button(
                "Amazon.co.jp を開く（注文履歴のダウンロード）",
                AMAZON_JP_HOME_URL,
                use_container_width=True,
            )
        with _lnk_ask:
            st.link_button(
                "アスクル（公式）を開く — 購入履歴 CSV",
                ASKUL_HOME_URL,
                use_container_width=True,
            )
        st.html(AMAZON_RECONCILE_DROPZONE_CSS)
        with st.container(border=True):
            _zu_a, _zu_k, _zu_r = st.columns(3, gap="large")
            with _zu_a:
                st.markdown("##### Amazon 注文履歴")
                st.caption("CSV をここにドラッグ＆ドロップ、または枠内をクリック")
                up_amazon_orders = st.file_uploader(
                    "Amazon 注文履歴 CSV",
                    type=["csv"],
                    key=f"{kp}up_amazon_orders",
                    label_visibility="collapsed",
                    help="法人アカウントの注文履歴レポート（支払い確定日・支払い金額・商品名 など）",
                )
            with _zu_k:
                st.markdown("##### アスクル購入履歴")
                st.caption("CSV をここにドラッグ＆ドロップ、または枠内をクリック")
                up_askul_orders = st.file_uploader(
                    "アスクル購入履歴 CSV",
                    type=["csv"],
                    key=f"{kp}up_askul_orders",
                    label_visibility="collapsed",
                    help="購入履歴（受付日・伝票番号・税込小計・商品名 など）",
                )
            with _zu_r:
                st.markdown("##### あおぞら口座明細（共通）")
                st.caption("CSV をここにドラッグ＆ドロップ、または枠内をクリック")
                up_aozora_match = st.file_uploader(
                    "あおぞら口座明細 CSV",
                    type=["csv"],
                    key=f"{kp}up_aozora_match",
                    label_visibility="collapsed",
                    help="Amazon・アスクル照合の両方で同じファイルを使えます。出金のある行が照合対象です。",
                )
        _btn_amz, _btn_ask = st.columns(2, gap="small")
        with _btn_amz:
            run_amazon_match = st.button("Amazon 照合を実行", type="primary", key=f"{kp}run_amazon_match")
        with _btn_ask:
            run_askul_match = st.button("アスクル 照合を実行", type="primary", key=f"{kp}run_askul_match")

        if run_amazon_match:
            if up_amazon_orders is None or up_aozora_match is None:
                st.error("Amazon 注文履歴とあおぞら明細の両方をアップロードしてください。")
            else:
                try:
                    raw_a = up_amazon_orders.getvalue()
                    raw_b = up_aozora_match.getvalue()
                    df_a = read_csv_auto(raw_a)
                    df_b = read_csv_auto(raw_b)
                    amz_tbl = build_amazon_payment_table(df_a)
                    bank_debits = filter_bank_visa_debit_rows(df_b)
                    matched, bank_only, amz_only = match_amazon_to_bank(
                        amz_tbl,
                        bank_debits,
                        date_tolerance_days=2,
                    )
                    st.subheader("Amazon × あおぞら — 照合結果（一致）")
                    if matched.empty:
                        st.info("条件に一致する組み合わせがありませんでした。")
                    else:
                        st.dataframe(matched, width="stretch", hide_index=True)
                        st.download_button(
                            "照合結果をCSVダウンロード",
                            data=matched.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"Amazon口座照合_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                            key=f"{kp}dl_amazon_match",
                        )
                    cbo, cam = st.columns(2)
                    with cbo:
                        st.markdown("**口座側のみ（未照合）**")
                        if bank_only.empty:
                            st.caption("なし")
                        else:
                            _bo = bank_only.drop(
                                columns=["_bank_date", "_out"], errors="ignore"
                            )
                            st.dataframe(_bo, width="stretch", hide_index=True)
                    with cam:
                        st.markdown("**Amazon 側のみ（未照合）**")
                        if amz_only.empty:
                            st.caption("なし")
                        else:
                            show_amz = amz_only.drop(
                                columns=["_ad", "_am"], errors="ignore"
                            )
                            st.dataframe(show_amz, width="stretch", hide_index=True)
                except Exception as e:
                    st.error(f"照合に失敗しました: {e}")

        if run_askul_match:
            if up_askul_orders is None or up_aozora_match is None:
                st.error("アスクル購入履歴とあおぞら明細の両方をアップロードしてください。")
            else:
                try:
                    raw_k = up_askul_orders.getvalue()
                    raw_b = up_aozora_match.getvalue()
                    df_k = read_csv_auto(raw_k)
                    df_b = read_csv_auto(raw_b)
                    ask_tbl = build_askul_payment_table(df_k)
                    bank_debits = filter_bank_visa_debit_rows(df_b)
                    matched_ask, bank_only_ask, ask_only = match_askul_to_bank(
                        ask_tbl,
                        bank_debits,
                        date_tolerance_days=2,
                    )
                    st.subheader("アスクル × あおぞら — 照合結果（一致）")
                    if matched_ask.empty:
                        st.info("条件に一致する組み合わせがありませんでした。")
                    else:
                        st.dataframe(matched_ask, width="stretch", hide_index=True)
                        st.download_button(
                            "照合結果をCSVダウンロード",
                            data=matched_ask.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"アスクル口座照合_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                            key=f"{kp}dl_askul_match",
                        )
                    cbo_k, cask = st.columns(2)
                    with cbo_k:
                        st.markdown("**口座側のみ（未照合）**")
                        if bank_only_ask.empty:
                            st.caption("なし")
                        else:
                            _bo_k = bank_only_ask.drop(
                                columns=["_bank_date", "_out"], errors="ignore"
                            )
                            st.dataframe(_bo_k, width="stretch", hide_index=True)
                    with cask:
                        st.markdown("**アスクル側のみ（未照合）**")
                        if ask_only.empty:
                            st.caption("なし")
                        else:
                            st.dataframe(ask_only, width="stretch", hide_index=True)
                except Exception as e:
                    st.error(f"アスクル照合に失敗しました: {e}")
