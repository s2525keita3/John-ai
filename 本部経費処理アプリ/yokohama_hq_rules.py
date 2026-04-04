"""
横浜信用金庫（本部経費）マスタルール。

- 取込対象外: 店舗計上・二重取得・内部振替など（常に集計・振分から除外）
- 本部固定額: 中退共 60,000 円、日新火災（軽自動車・伊藤・石田）6,000 円
"""
from __future__ import annotations

import re

import pandas as pd

# 照合テキストに「すべて含む」必要があるキーワード（順不同・部分一致）
# 誤マッチを減らすため複数キーワードで縛る
_EXCLUDE_ALL: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "uc_tialink",
        "UCカード・Tialink（各拠点固定電話・本部取込対象外）",
        ("UC", "Tialink"),
    ),
    (
        "amex_usage",
        "アメックス・カード使用分（個別明細で取得のため除外）",
        ("アメックス", "カード使用"),
    ),
    (
        "tax_refund",
        "国税還付金（雑収入・本部取込対象外）",
        ("国税還付", "源泉"),
    ),
    (
        "tax_refund_alt",
        "横浜中税務署・還付（雑収入・本部取込対象外）",
        ("横浜中税務署", "還付"),
    ),
    (
        "payroll_ito",
        "伊藤裕美子・給料（支給控除から取得のため除外）",
        ("伊藤裕美子", "給料"),
    ),
    (
        "john_transfer",
        "株式会社ジョンへの資金移動（内部振替・除外）",
        ("株式会社ジョン", "資金移動"),
    ),
    (
        "asahi_provider",
        "ASAHIネット・プロバイダー（各店舗計上のため除外）",
        ("ASAHI", "プロバイダー"),
    ),
]

# 金額上書き: (rule_id, 説明, キーワード全一致, 本部計上額, 備考メモ)
_AMOUNT_OVERRIDES: list[tuple[str, str, tuple[str, ...], float, str]] = [
    (
        "chutaikyo",
        "中小企業退職金共済（本部60,000円固定）",
        ("中小企業退職金共済",),
        60_000.0,
        "通帳額は全額掛金。本部計上は60,000円固定。",
    ),
    (
        "nissin_fire",
        "日新火災・損害保険料（軽自動車・伊藤・石田・本部6,000円固定）",
        ("日新火災", "損害保険"),
        6_000.0,
        "通帳額は契約全体。本部計上は軽自動車6,000円（伊藤・石田）。",
    ),
]


def _yokohama_match_text(row: pd.Series) -> str:
    """科目・支払先・摘要を結合（app._combine_yokohama_summary と同じ考え方）。"""
    cols = [c for c in ("科目", "支払先", "摘要") if c in row.index]
    if not cols:
        return str(row.get("摘要", "") or "").strip()
    acc = str(row.get(cols[0], "") or "").strip()
    for c in cols[1:]:
        acc = acc + " " + str(row.get(c, "") or "").strip()
    return re.sub(r"\s+", " ", acc).strip()


def apply_yokohama_hq_master_rules(df: pd.DataFrame) -> pd.DataFrame:
    """
    横浜信金取引に「取込対象外」「出金額_通帳」「本部調整メモ」を付与。
    取込対象外の行は出金額上書きを行わない。
    """
    out = df.copy()
    if out.empty:
        return out

    out["取込対象外"] = False
    out["取込対象外理由"] = ""
    out["本部調整メモ"] = ""

    texts: list[str] = []
    for _, row in out.iterrows():
        texts.append(_yokohama_match_text(row))

    reasons: list[str] = [""] * len(out)
    excluded: list[bool] = [False] * len(out)
    for i, tx in enumerate(texts):
        for _rid, reason, kws in _EXCLUDE_ALL:
            if all(k in tx for k in kws):
                excluded[i] = True
                reasons[i] = reason
                break

    out["取込対象外"] = excluded
    out["取込対象外理由"] = reasons

    # 通帳の出金額を保持（列名は出金額に統一済み想定）
    amt_col = "出金額"
    if amt_col not in out.columns:
        return out

    orig_vals = pd.to_numeric(out[amt_col], errors="coerce").fillna(0.0).tolist()
    out["出金額_通帳"] = orig_vals
    adjusted_note: list[str] = [""] * len(out)

    for i, tx in enumerate(texts):
        if excluded[i]:
            continue
        for _rid, _desc, kws, new_amt, memo in _AMOUNT_OVERRIDES:
            if all(k in tx for k in kws):
                if abs(orig_vals[i] - new_amt) > 0.01:
                    out.iat[i, out.columns.get_loc(amt_col)] = new_amt
                adjusted_note[i] = memo
                break

    out["本部調整メモ"] = adjusted_note

    return out
