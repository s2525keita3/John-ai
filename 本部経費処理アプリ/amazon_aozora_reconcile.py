"""
Amazon 注文履歴 CSV とあおぞら口座明細 CSV の照合（金額一致 + 支払確定日と口座日の ±2 日）。
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Any

import pandas as pd


def _normalize_header_name(c: Any) -> str:
    """列名の BOM・前後空白・全角英数字を正規化（あおぞら以外のCSVにも対応）。"""
    if c is None or (isinstance(c, float) and pd.isna(c)):
        return ""
    s = unicodedata.normalize("NFKC", str(c)).strip()
    return s.lstrip("\ufeff").strip()


def normalize_bank_statement_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    口座明細を照合用に「日付」「出金額」「摘要」に寄せる。
    GMOあおぞら標準のほか、取引日・利用日・金額のみの明細なども拾う。
    """
    out = df.copy()
    out.columns = [_normalize_header_name(c) for c in out.columns]
    # 空列名は pandas が重複扱いしうるので一意化
    seen: dict[str, int] = {}
    new_cols: list[str] = []
    for c in out.columns:
        if c == "":
            c = f"_unnamed_{len(new_cols)}"
        base = c
        if base in seen:
            seen[base] += 1
            c = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        new_cols.append(c)
    out.columns = new_cols

    # 別名 → 標準名（先に長い／具体的な名前を優先）
    _DATE_ALIASES = (
        "取引年月日",
        "お取引日付",
        "取引日付",
        "お取引日",
        "取引日",
        "ご利用日",
        "利用日",
        "日付",
    )
    _OUT_ALIASES = (
        "出金金額",  # あおぞら等で「出金額」と表記されることがある
        "出金額",
        "御出金額",
        "お支払金額",
        "支払い金額",
        "支払金額",
        "ご利用金額",
        "利用金額",
        "出金",
    )
    _SUMMARY_ALIASES = (
        "摘要",
        "お取引内容",
        "取引内容",
        "ご利用内容",
        "利用内容",
        "内容",
        "備考",
        "摘要欄",
    )

    def _pick_rename(
        target: str,
        aliases: tuple[str, ...],
        columns: list[str],
    ) -> dict[str, str]:
        if target in columns:
            return {}
        for a in aliases:
            if a in columns:
                return {a: target}
        return {}

    cols = list(out.columns)
    r: dict[str, str] = {}
    r.update(_pick_rename("日付", _DATE_ALIASES, cols))
    if r:
        out = out.rename(columns=r)
        cols = list(out.columns)

    r2: dict[str, str] = {}
    r2.update(_pick_rename("出金額", _OUT_ALIASES, cols))
    if r2:
        out = out.rename(columns=r2)
        cols = list(out.columns)

    r3: dict[str, str] = {}
    r3.update(_pick_rename("摘要", _SUMMARY_ALIASES, cols))
    if r3:
        out = out.rename(columns=r3)

    # 「金額」1列のみ（入金・出金が別列にない）— カード明細など
    if "出金額" not in out.columns and "入金額" not in out.columns:
        if "金額" in out.columns:
            out = out.rename(columns={"金額": "出金額"})

    # 日付がまだ無いとき、列名に「日付」「取引」が含まれる列を1つだけ採用
    if "日付" not in out.columns:
        for c in out.columns:
            if "日付" in c or c in ("取引日時", "利用日時"):
                out = out.rename(columns={c: "日付"})
                break

    return out


def _parse_yyyymmdd(s: Any) -> date | None:
    if pd.isna(s) or s is None:
        return None
    t = str(s).strip().replace("/", "").replace("-", "")
    if len(t) >= 8 and t[:8].isdigit():
        y, m, d = int(t[:4]), int(t[4:6]), int(t[6:8])
        try:
            return date(y, m, d)
        except ValueError:
            return None
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.date()
    except Exception:
        return None


def _parse_amazon_cell_date(v: Any) -> date | None:
    if pd.isna(v) or v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if s in ("", "該当無し", "-"):
        return None
    dt = pd.to_datetime(v, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).date()


def _parse_money(v: Any) -> float | None:
    if pd.isna(v) or v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace(",", "").replace("¥", "").replace('"', "")
    if s == "" or s in ("-", "—", "該当無し"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _clean_pay_auth_id(v: Any) -> str:
    """Excel の =\"...\" 形式や前後引用符を除いた支払認証・請求書ID。"""
    if pd.isna(v) or v is None:
        return ""
    s = unicodedata.normalize("NFKC", str(v)).strip().strip('"').strip("'")
    if s.startswith("="):
        s = s[1:].strip().strip('"').strip("'")
    if s in ("", "該当無し", "-", "nan"):
        return ""
    return s


def _agg_order_payment_amount(series: pd.Series) -> float:
    """
    同一注文内の支払い金額列を1つの請求額にまとめる。
    - 行ごとに同じ合計が繰り返されている場合はその値（max）
    - 行ごとに内訳が違う場合は合計（sum）
    """
    parsed: list[float] = []
    for x in series:
        v = _parse_money(x)
        if v is not None and v > 0:
            parsed.append(v)
    if not parsed:
        return float("nan")
    if len(set(parsed)) == 1:
        return float(parsed[0])
    return float(sum(parsed))


def build_amazon_payment_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    法人向け注文履歴（1 行 1 商品）を **口座の引落とし単位** に近い形に集約する。

    - **口座と突き合わせる金額**は **支払い金額**（分割カード決済は行ごとに同じ注文でも別額・別IDになり得る）。
    - **注文の合計（税込）**は注文全体の合計であり、分割請求の合計とは別物なので照合の主キーにしない。
    - **支払認証ID/請求書番号** が列にあるときは **同一注文でも ID が違えば別の引落とし**として行を分ける
      （例: 同じ注文で 1161 円 × 複数回の Visa 承認 → 口座も複数行）。
    - **商品の価格（税込）**は明細単位。照合は **支払い金額** を使う。

    必須列: 支払い確定日, 支払い金額。推奨: 注文番号、支払認証ID/請求書番号
    """
    need = ("支払い確定日", "支払い金額")
    for c in need:
        if c not in df.columns:
            raise ValueError(f"Amazon CSV に「{c}」列がありません。列: {list(df.columns)}")

    work = df.copy()
    work["_pay_date"] = work["支払い確定日"].map(_parse_amazon_cell_date)
    work = work[work["_pay_date"].notna()]
    if work.empty:
        return pd.DataFrame(
            columns=[
                "Amazon支払確定日",
                "Amazon支払金額",
                "商品概要（抜粋）",
                "注文番号",
                "アカウントユーザー",
            ]
        )

    # 注文番号（無い行は行単位で区別）
    if "注文番号" in work.columns:
        work["_oid"] = work["注文番号"].fillna("").astype(str).str.strip()
        _empty = work["_oid"] == ""
        work.loc[_empty, "_oid"] = "__単独行__" + work.loc[_empty].index.astype(str)
    else:
        work["_oid"] = "__単独行__" + work.index.astype(str)

    # 分割請求: 支払認証IDが異なれば別グループ（口座の複数行と対応）
    _pay_id_col = _find_column(
        work,
        ("支払認証ID/請求書番号", "支払認証ID", "請求書番号"),
    )
    if _pay_id_col:
        work["_pid"] = work[_pay_id_col].map(_clean_pay_auth_id)
    else:
        work["_pid"] = ""

    def _agg_names(series: pd.Series) -> str:
        parts: list[str] = []
        for x in series.dropna().astype(str).str.strip():
            if x and x not in parts:
                parts.append(x[:120])
            if len(parts) >= 15:
                break
        return " ／ ".join(parts) if parts else ""

    # _pid あり: (日付, 注文, 支払ID) で分割。_pid なし: 空文字で従来どおり注文×日付でまとめる
    gcols = ["_pay_date", "_oid", "_pid"]
    agg_map: dict[str, Any] = {
        "支払い金額": _agg_order_payment_amount,
    }
    if "商品名" in work.columns:
        agg_map["商品名"] = _agg_names
    if "注文番号" in work.columns:
        agg_map["注文番号"] = lambda s: ", ".join(
            dict.fromkeys(s.dropna().astype(str).str.strip().tolist())
        )[:500]
    if "アカウントユーザー" in work.columns:
        agg_map["アカウントユーザー"] = "first"

    out = work.groupby(gcols, as_index=False).agg(agg_map)
    out = out.rename(
        columns={
            "_pay_date": "Amazon支払確定日",
            "支払い金額": "Amazon支払金額",
        }
    )
    out = out.drop(columns=["_oid", "_pid"], errors="ignore")
    if "商品名" in out.columns:
        out = out.rename(columns={"商品名": "商品概要（抜粋）"})
    out = out[out["Amazon支払金額"].notna() & (pd.to_numeric(out["Amazon支払金額"], errors="coerce") > 0)]
    return out


def _format_match_date_cell(v: Any) -> str:
    """照合結果 CSV 用に日付を YYYY-MM-DD 文字列へ。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return str(v).strip()
    return pd.Timestamp(ts).date().isoformat()


def filter_bank_visa_debit_rows(bank_df: pd.DataFrame) -> pd.DataFrame:
    """
    口座明細のうち **出金がある行だけ** を返す（摘要は絞らない）。
    Amazon 側と **金額一致 + 日付 ±N 日** でだけ照合するシンプルな前提。
    """
    b = normalize_bank_statement_columns(bank_df)
    if "出金額" not in b.columns or "日付" not in b.columns:
        raise ValueError(
            "口座 CSV に「日付」と「出金額」（または同義の列）が必要です。"
            f" 元の列: {list(bank_df.columns)} / 正規化後: {list(b.columns)}"
        )
    b = b.copy()
    amt = pd.to_numeric(b["出金額"], errors="coerce").fillna(0.0)
    b = b[amt > 0]
    return b


def match_amazon_to_bank(
    amazon_payments: pd.DataFrame,
    bank_rows: pd.DataFrame,
    *,
    date_tolerance_days: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    戻り値: (照合結果表, 口座のみ, Amazonのみ)
    """
    bank_rows = bank_rows.copy()
    bank_rows["_bank_date"] = bank_rows["日付"].map(_parse_yyyymmdd)
    bank_rows["_out"] = pd.to_numeric(bank_rows["出金額"], errors="coerce").fillna(0.0)
    bank_rows = bank_rows[bank_rows["_bank_date"].notna() & (bank_rows["_out"] > 0)]

    amap = amazon_payments.copy()
    if "Amazon支払確定日" not in amap.columns or "Amazon支払金額" not in amap.columns:
        raise ValueError("集約済み Amazon 表の形式が不正です。")
    amap["_ad"] = amap["Amazon支払確定日"].map(
        lambda x: x if isinstance(x, date) else _parse_yyyymmdd(x)
    )
    amap["_am"] = pd.to_numeric(amap["Amazon支払金額"], errors="coerce")

    used_bank: set[Any] = set()
    used_amz: set[Any] = set()
    matches: list[dict[str, Any]] = []

    for bi, brow in bank_rows.iterrows():
        bd = brow["_bank_date"]
        ba = float(brow["_out"])
        best_aj: Any = None
        best_delta: int | None = None
        for aj, arow in amap.iterrows():
            if aj in used_amz:
                continue
            if abs(float(arow["_am"]) - ba) > 0.5:
                continue
            ad = arow["_ad"]
            if ad is None or pd.isna(ad):
                continue
            delta = abs((bd - ad).days) if isinstance(ad, date) else 999
            if delta > date_tolerance_days:
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_aj = aj
        if best_aj is not None:
            used_bank.add(bi)
            used_amz.add(best_aj)
            arow = amap.loc[best_aj]
            ad_raw = arow.get("Amazon支払確定日", "")
            ad = _format_match_date_cell(ad_raw)
            matches.append(
                {
                    "口座取引日": brow.get("日付", ""),
                    "Amazon支払確定日": ad,
                    "Amazon支払金額": arow.get("Amazon支払金額", ""),
                    "注文商品概要": arow.get("商品概要（抜粋）", arow.get("商品名", "")),
                }
            )

    matched_bank_idx = set(used_bank)
    bank_only = bank_rows.loc[[i for i in bank_rows.index if i not in matched_bank_idx]]
    amz_only = amap.loc[[i for i in amap.index if i not in used_amz]]

    _match_cols = [
        "口座取引日",
        "Amazon支払確定日",
        "Amazon支払金額",
        "注文商品概要",
    ]
    match_df = pd.DataFrame(matches, columns=_match_cols) if matches else pd.DataFrame(columns=_match_cols)
    return match_df, bank_only, amz_only
