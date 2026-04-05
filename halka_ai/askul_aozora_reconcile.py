"""
アスクル購入履歴 CSV とあおぞら口座明細の照合（金額一致 + 受付日と口座日の ±2 日）。
amazon_aozora_reconcile のマッチングを流用。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from amazon_aozora_reconcile import (
    _parse_amazon_cell_date,
    _parse_money,
    match_amazon_to_bank,
)


def build_askul_payment_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    購入履歴（行単位）を **伝票番号＋受付日** ごとに集計し、口座の1引落としに近い単位にする。

    必須列: 受付日, 税込小計, 伝票番号
    任意: 商品名（値引は税込小計が負の行として合算される）
    """
    need = ("受付日", "税込小計", "伝票番号")
    for c in need:
        if c not in df.columns:
            raise ValueError(f"アスクル CSV に「{c}」列がありません。列: {list(df.columns)}")

    work = df.copy()
    work["_pay_date"] = work["受付日"].map(_parse_amazon_cell_date)
    work["_amt_line"] = work["税込小計"].map(_parse_money)
    work["_amt_line"] = pd.to_numeric(work["_amt_line"], errors="coerce").fillna(0.0)
    work = work[work["_pay_date"].notna()]
    if work.empty:
        return pd.DataFrame(
            columns=[
                "Askul受付日",
                "Askul金額_税込",
                "商品概要（抜粋）",
                "伝票番号",
            ]
        )

    work["_oid"] = work["伝票番号"].fillna("").astype(str).str.strip()
    _e = work["_oid"] == ""
    work.loc[_e, "_oid"] = "__単独行__" + work.loc[_e].index.astype(str)

    def _agg_names(series: pd.Series) -> str:
        parts: list[str] = []
        for x in series.dropna().astype(str).str.strip():
            if x and x not in parts:
                parts.append(x[:100])
            if len(parts) >= 12:
                break
        return " ／ ".join(parts) if parts else ""

    gcols = ["_pay_date", "_oid"]

    agg_map: dict[str, Any] = {
        "Askul金額_税込": ("_amt_line", "sum"),
        "伝票番号": ("伝票番号", "first"),
    }
    if "商品名" in work.columns:
        agg_map["商品概要（抜粋）"] = ("商品名", _agg_names)

    out = work.groupby(gcols, as_index=False).agg(**agg_map)
    out = out.rename(columns={"_pay_date": "Askul受付日"})
    out = out.drop(columns=["_oid"], errors="ignore")
    out = out[out["Askul金額_税込"].notna() & (pd.to_numeric(out["Askul金額_税込"], errors="coerce") > 0)]
    if "商品概要（抜粋）" not in out.columns:
        out["商品概要（抜粋）"] = ""
    return out


def match_askul_to_bank(
    askul_payments: pd.DataFrame,
    bank_rows: pd.DataFrame,
    *,
    date_tolerance_days: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    戻り値: (照合結果, 口座のみ, アスクルのみ)
    """
    tmp = askul_payments.copy()
    if "商品概要（抜粋）" not in tmp.columns:
        tmp["商品概要（抜粋）"] = ""
    tmp = tmp.rename(
        columns={
            "Askul受付日": "Amazon支払確定日",
            "Askul金額_税込": "Amazon支払金額",
        }
    )
    m, bank_only, amz_only = match_amazon_to_bank(
        tmp,
        bank_rows,
        date_tolerance_days=date_tolerance_days,
    )
    if not m.empty:
        m = m.rename(
            columns={
                "Amazon支払確定日": "Askul受付日",
                "Amazon支払金額": "Askul金額（税込）",
                "注文商品概要": "商品概要",
            }
        )
    else:
        m = pd.DataFrame(
            columns=["口座取引日", "Askul受付日", "Askul金額（税込）", "商品概要"],
        )

    show_askul = amz_only.drop(columns=["_ad", "_am"], errors="ignore")
    ren = {
        "Amazon支払確定日": "Askul受付日",
        "Amazon支払金額": "Askul金額_税込",
    }
    show_askul = show_askul.rename(columns={k: v for k, v in ren.items() if k in show_askul.columns})
    return m, bank_only, show_askul
