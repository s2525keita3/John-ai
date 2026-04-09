from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import pdfplumber
import streamlit as st

from report_parser import summarize_report_pdf
from service_fees import MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT, add_revenue_columns


def _read_app_version() -> str:
    """デプロイ確認用（VERSION の先頭行）。"""
    try:
        line = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip().splitlines()
        return line[0] if line else "?"
    except OSError:
        return "?"


# 介護保険の概算売上は「介護」側（10割・高い方）単価のみ（支援按分は UI から廃止）
SUPPORT_RATIO_FOR_FEES = 0.0

# 集計表・CSV・コード別グラフで共通する表示名（DataFrame の列キーは「他」「記録」のまま）
REPORT_SUMMARY_EXTRA_COLUMN_LABELS: dict[str, str] = {
    "他": "他（サマリー・1回=60分）",
    "記録": "記録（サマリー・1回=60分）",
}

# コード別グラフ・表の列（区分）の並び
CODE_CATEGORY_DISPLAY_ORDER: list[str] = [
    "P60",
    "Ⅰ-5×2 PTOT40",
    "Ⅰ-5 PTOT20",
    "Ⅰ-2 訪看2",
    "Ⅰ-3 訪看3",
    "Ⅰ-4 訪看4",
    REPORT_SUMMARY_EXTRA_COLUMN_LABELS["他"],
    REPORT_SUMMARY_EXTRA_COLUMN_LABELS["記録"],
    "医療（サマリー）",
    "同行(2回目)",
]


def _sort_report_df_by_pdf_order(df: pd.DataFrame) -> pd.DataFrame:
    """担当別集計を PDF ブロック先頭位置（_pdf_order）で並べ替え。表示のたびに呼ぶ。"""
    out = df.copy()
    if not out.empty and "_pdf_order" in out.columns:
        out = out.sort_values(
            ["_pdf_order", "担当者"],
            ascending=[True, True],
            kind="mergesort",
        )
    return out


def _reorder_report_columns_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """他・記録を 90 と 医療の間に置き、横スクロールで見落とされにくくする。"""
    preferred = [
        "担当者",
        "20",
        "30",
        "40",
        "60",
        "90",
        "他",
        "記録",
        "医療",
        "医療保険暫定(円)",
        "同行",
        "件数",
        "概算売上(円)",
        "売上/時間(円/h)",
    ]
    head = [c for c in preferred if c in df.columns]
    tail = [c for c in df.columns if c not in head]
    return df[head + tail]


def _report_visit_table_column_config(df: pd.DataFrame) -> dict:
    """担当別集計表の列表示名。サマリー由来の「他」「記録」を説明付きで見せる。"""
    cfg: dict = {}
    if "他" in df.columns:
        cfg["他"] = st.column_config.NumberColumn(
            REPORT_SUMMARY_EXTRA_COLUMN_LABELS["他"],
            help="帳票サマリーの「他: ○回」から読んだ回数。1回＝60分として合計時間（件数）に加算します。",
            format="%d",
        )
    if "記録" in df.columns:
        cfg["記録"] = st.column_config.NumberColumn(
            REPORT_SUMMARY_EXTRA_COLUMN_LABELS["記録"],
            help="帳票サマリーの「記録: ○回」から読んだ回数。1回＝60分として合計時間（件数）に加算します。",
            format="%d",
        )
    return cfg


def add_medical_insurance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """医療件数×暫定単価を列に追加（集計表・CSVとダッシュボードで一致）。"""
    out = df.copy()
    if "医療" not in out.columns:
        return out
    med = pd.to_numeric(out["医療"], errors="coerce").fillna(0).astype(int)
    out["医療保険暫定(円)"] = (med * MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT).astype(int)
    # 列順: 「医療」の直後に医療保険暫定（CSVを見やすく）
    if "医療" in out.columns:
        cols = [c for c in out.columns if c != "医療保険暫定(円)"]
        idx = cols.index("医療") + 1
        cols = cols[:idx] + ["医療保険暫定(円)"] + cols[idx:]
        out = out[cols]
    return out


try:
    import altair as alt

    _HAS_ALTAIR = True
except ImportError:
    _HAS_ALTAIR = False


@dataclass(frozen=True)
class VisitRow:
    date: str
    staff: str
    place: str
    category: str
    source: str
    raw: str


DEFAULT_CATEGORIES = [
    "未分類",
    "新規",
    "既存",
    "ルート",
    "クレーム",
    "集金",
    "その他",
    "除外",
]


def _normalize_text(s: str) -> str:
    s = s.replace("\u3000", " ").strip()
    s = re.sub(r"[ \t]+", " ", s)
    return s


def _guess_category(text: str) -> str:
    t = text.lower()
    rules = [
        (["新規", "初回", "新店"], "新規"),
        (["既存", "継続", "定期"], "既存"),
        (["ルート", "巡回"], "ルート"),
        (["クレーム", "苦情", "対応"], "クレーム"),
        (["集金", "回収", "入金"], "集金"),
        (["除外", "キャンセル", "中止"], "除外"),
    ]
    for keys, cat in rules:
        if any(k.lower() in t for k in keys):
            return cat
    return "未分類"


def _extract_date(text: str) -> str:
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = pd.Timestamp.today().year
        return f"{y}-{mo:02d}-{d:02d}"
    return ""


def parse_pdf(file_bytes: bytes, filename: str) -> list[VisitRow]:
    rows: list[VisitRow] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = _normalize_text(line)
                if not line:
                    continue
                date = _extract_date(line)
                category = _guess_category(line)
                rows.append(
                    VisitRow(
                        date=date,
                        staff="",
                        place="",
                        category=category,
                        source=f"PDF:{filename}",
                        raw=line,
                    )
                )
    return rows


def _extract_full_text_from_pdf(file_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    return "\n".join(pages)


def _count同行_from_text(text: str) -> dict[str, int]:
    """
    PDF末尾の「副)2回目訪問」一覧を基準に同行回数を数える。
    """
    counts: dict[str, int] = {}
    for line in text.splitlines():
        line = _normalize_text(line)
        if not line.startswith("副)2回目訪問"):
            continue
        # 末尾に「姓 名」が来る想定
        parts = [p for p in re.split(r"\s+", line) if p]
        if len(parts) < 3:
            continue
        staff = " ".join(parts[-2:])
        counts[staff] = counts.get(staff, 0) + 1
    return counts


def _extract_medical_count_from_block(block_text: str) -> int:
    """
    サマリー部にある「xx回 / yy回 / xx日 / yy日 / xx分 / yy分」形式から医療回数(yy回)を取る。
    抽出に失敗したら 0。
    """
    m = re.search(
        r"\n(\d+)回\s*\n(\d+)回\s*\n(\d+)日\s*\n(\d+)日\s*\n(\d+)分\s*\n(\d+)分\s*\n",
        block_text,
    )
    if not m:
        return 0
    return int(m.group(2))


def _count_occurrences(block_text: str, needle: str) -> int:
    return len(re.findall(re.escape(needle), block_text))


def summarize_monthly_visit_hours_from_report_pdf(file_bytes: bytes) -> pd.DataFrame:
    # 後方互換：古い呼び出し箇所のために残す
    return summarize_report_pdf(file_bytes)


def parse_table_file(df: pd.DataFrame, source: str) -> list[VisitRow]:
    cols = {c: str(c).strip() for c in df.columns}
    df = df.rename(columns=cols)

    def pick(colnames: Iterable[str]) -> Optional[str]:
        for c in df.columns:
            if str(c).strip().lower() in {x.lower() for x in colnames}:
                return c
        for c in df.columns:
            for x in colnames:
                if x.lower() in str(c).strip().lower():
                    return c
        return None

    c_date = pick(["日付", "date", "訪問日", "実施日"])
    c_staff = pick(["担当", "担当者", "staff", "営業", "氏名", "名前"])
    c_place = pick(["訪問先", "得意先", "顧客", "会社", "店舗", "place"])
    c_cat = pick(["区分", "カテゴリ", "分類", "category", "種別"])
    c_raw = pick(["メモ", "内容", "備考", "摘要", "raw", "詳細", "コメント"])

    rows: list[VisitRow] = []
    for _, r in df.iterrows():
        raw_parts = []
        for c in [c_raw, c_place, c_staff, c_cat, c_date]:
            if c and pd.notna(r.get(c)):
                raw_parts.append(str(r.get(c)))
        raw = _normalize_text(" / ".join(raw_parts))

        date = ""
        if c_date and pd.notna(r.get(c_date)):
            date = _extract_date(str(r.get(c_date)))
        if not date:
            date = _extract_date(raw)

        staff = _normalize_text(str(r.get(c_staff))) if c_staff and pd.notna(r.get(c_staff)) else ""
        place = _normalize_text(str(r.get(c_place))) if c_place and pd.notna(r.get(c_place)) else ""

        category = ""
        if c_cat and pd.notna(r.get(c_cat)):
            category = _normalize_text(str(r.get(c_cat)))
        if not category:
            category = _guess_category(raw)

        rows.append(
            VisitRow(
                date=date,
                staff=staff,
                place=place,
                category=category,
                source=source,
                raw=raw,
            )
        )
    return rows


def load_file_to_rows(uploaded) -> list[VisitRow]:
    name = uploaded.name
    data = uploaded.getvalue()
    lower = name.lower()

    if lower.endswith(".pdf"):
        return parse_pdf(data, name)

    if lower.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data))
        return parse_table_file(df, f"CSV:{name}")

    if lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(data))
        return parse_table_file(df, f"Excel:{name}")

    return []


def rows_to_df(rows: list[VisitRow]) -> pd.DataFrame:
    return pd.DataFrame([r.__dict__ for r in rows])


def _apply_staff_filter(df: pd.DataFrame, ex: set[str], inc: set[str]) -> pd.DataFrame:
    """除外・限定の担当者名フィルタ（集計表とダッシュボードで共通）。"""
    out = df.copy()
    if ex and "担当者" in out.columns:
        out = out[~out["担当者"].isin(ex)]
    if inc and "担当者" in out.columns:
        out = out[out["担当者"].isin(inc)]
    return out


def _code_aggregate_row(df: pd.DataFrame) -> dict[str, int]:
    """コード別の件数合計（訪看3とP60は分離）。表示用ラベル付き。"""
    row: dict[str, int] = {}
    if "20" in df.columns:
        row["Ⅰ-5 PTOT20"] = int(df["20"].sum())
    if "30" in df.columns:
        row["Ⅰ-2 訪看2"] = int(df["30"].sum())
    if "40" in df.columns:
        row["Ⅰ-5×2 PTOT40"] = int(df["40"].sum())
    if "_vis3" in df.columns:
        row["Ⅰ-3 訪看3"] = int(df["_vis3"].sum())
    if "_p60" in df.columns:
        row["P60"] = int(df["_p60"].sum())
    if "60" in df.columns and "_vis3" not in df.columns and "_p60" not in df.columns:
        row["列60（訪看3／P60 未分離）"] = int(df["60"].sum())
    if "90" in df.columns:
        row["Ⅰ-4 訪看4"] = int(df["90"].sum())
    if "他" in df.columns:
        row[REPORT_SUMMARY_EXTRA_COLUMN_LABELS["他"]] = int(df["他"].sum())
    if "記録" in df.columns:
        row[REPORT_SUMMARY_EXTRA_COLUMN_LABELS["記録"]] = int(df["記録"].sum())
    if "医療" in df.columns:
        row["医療（サマリー）"] = int(df["医療"].sum())
    if "同行" in df.columns:
        row["同行(2回目)"] = int(df["同行"].sum())
    return row


def _order_code_aggregate(row: dict[str, int]) -> dict[str, int]:
    """コード別の表示順を CODE_CATEGORY_DISPLAY_ORDER に合わせ、未定義キーは末尾へ。"""
    out: dict[str, int] = {}
    for key in CODE_CATEGORY_DISPLAY_ORDER:
        if key in row:
            out[key] = row[key]
    for key, val in row.items():
        if key not in out:
            out[key] = val
    return out


def _render_code_aggregates(df: pd.DataFrame) -> None:
    """コード別合計テーブル（訪看3／P60 分離）。"""
    st.markdown("###### コード別（件数）")
    st.caption("表示中の担当のみ。列「60」は訪看3（_vis3）と P60 を分けて集計しています。")
    row = _order_code_aggregate(_code_aggregate_row(df))
    if row:
        st.dataframe(pd.DataFrame([row]), use_container_width=True, hide_index=True)


def _render_code_charts(df: pd.DataFrame) -> None:
    """コード別件数の棒グラフ（訪看3・P60 分離）。"""
    row = _order_code_aggregate(_code_aggregate_row(df))
    if not row:
        return
    keys_ordered = list(row.keys())
    chart_df = pd.DataFrame({"区分": keys_ordered, "件数": list(row.values())})
    if _HAS_ALTAIR and len(chart_df) > 0:
        bc1, bc2 = st.columns(2, gap="large")
        with bc1:
            st.caption("棒グラフ")
            st.bar_chart(chart_df.set_index("区分"), use_container_width=True, height=320)
        pie = (
            alt.Chart(chart_df)
            .mark_arc(innerRadius=50, padAngle=0.02)
            .encode(
                theta=alt.Theta("件数:Q", stack=True),
                color=alt.Color(
                    "区分:N",
                    sort=keys_ordered,
                    legend=alt.Legend(orient="right", title=None),
                ),
                tooltip=["区分", "件数"],
            )
            .properties(height=320)
        )
        with bc2:
            st.caption("構成比")
            st.altair_chart(pie, use_container_width=True)
    else:
        st.caption("棒グラフ")
        st.bar_chart(chart_df.set_index("区分"), use_container_width=True, height=320)


def _render_report_dashboard_section(rdf2: pd.DataFrame) -> None:
    """集計表の直下に置く全幅ダッシュボード（数値・職種・コード別）。"""
    rdf_fee = add_revenue_columns(rdf2, SUPPORT_RATIO_FOR_FEES)
    total_minutes = int(rdf2["_分数合計"].sum()) if "_分数合計" in rdf2.columns else 0
    total同行 = int(rdf2["同行"].sum()) if "同行" in rdf2.columns else 0
    total_rev = int(rdf_fee["概算売上(円)"].sum()) if "概算売上(円)" in rdf_fee.columns else 0
    med_cnt = int(rdf2["医療"].sum()) if "医療" in rdf2.columns else 0
    med_yen = med_cnt * MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT
    avg_yen_h = total_rev / (total_minutes / 60.0) if total_minutes > 0 else 0.0

    with st.container(border=True):
        st.markdown("###### サマリー")
        k1, k2, k3 = st.columns(3)
        k1.metric("時間合計", f"{total_minutes / 60:.2f} h")
        k2.metric("概算売上（介護＋医療暫定）", f"{total_rev:,} 円")
        k3.metric("医療暫定（内訳）", f"{med_yen:,} 円")
        k4, k5 = st.columns(2)
        k4.metric("同行（2回目）", f"{total同行:,} 回")
        k5.metric("平均 売上／時間", f"{avg_yen_h:,.0f} 円/h" if total_minutes > 0 else "—")

    st.caption(
        "概算売上は介護（支援/介護区分）の利用料に、医療件数×"
        f"{MEDICAL_INSURANCE_FLAT_YEN_PER_VISIT:,} 円／回の医療暫定を加算した合計です。"
        " PDFで支援と介護の区切りが取れた担当は区分ごとの単価、区切りが無い担当は介護単価のみ（上の表と同じ）。"
    )

    if "_職種" in rdf2.columns and "_分数合計" in rdf2.columns:
        by_role = rdf2.groupby("_職種", dropna=False)["_分数合計"].sum().reset_index()
        by_role["時間"] = by_role["_分数合計"] / 60.0
        rev_by = rdf_fee.groupby("_職種", dropna=False)["概算売上(円)"].sum().reset_index()
        by_role = by_role.merge(rev_by, on="_職種", how="left")
        by_role = by_role.rename(columns={"_職種": "職種", "_分数合計": "分数合計"})
        by_role["売上/時間"] = by_role.apply(
            lambda r: round(r["概算売上(円)"] / r["時間"]) if r["時間"] and r["時間"] > 0 else 0.0,
            axis=1,
        )
        show_br = by_role[["職種", "分数合計", "時間", "概算売上(円)", "売上/時間"]]
        with st.container(border=True):
            st.markdown("###### 職種別")
            st.caption("分数・時間・概算売上（介護＋医療暫定、上の集計表と同一データ）")
            tb, ch = st.columns((1.05, 1), gap="large")
            with tb:
                st.dataframe(show_br, use_container_width=True, hide_index=True)
            with ch:
                br = by_role[["職種", "概算売上(円)"]].copy()
                st.caption("概算売上（棒）")
                st.bar_chart(br.set_index("職種"), use_container_width=True, height=260)
                if _HAS_ALTAIR and not br.empty:
                    pie_r = (
                        alt.Chart(br)
                        .mark_arc(innerRadius=42, padAngle=0.02)
                        .encode(
                            theta=alt.Theta("概算売上(円):Q"),
                            color=alt.Color("職種:N", legend=alt.Legend(title=None)),
                            tooltip=["職種", "概算売上(円)"],
                        )
                        .properties(height=260)
                    )
                    st.caption("構成比")
                    st.altair_chart(pie_r, use_container_width=True)

    st.divider()
    with st.container(border=True):
        _render_code_aggregates(rdf2)
        _render_code_charts(rdf2)

    st.caption("上の集計表・ダッシュボードは同一データです。担当の絞り込みはサイドバーの「表示の絞り込み」に連動します。")


st.set_page_config(page_title="訪問件数仕分け", layout="wide")
st.title("訪問件数仕分け")

st.caption(
    "担当別訪問件数PDFを取り込み、ルールに沿って集計します。"
    "担当者名は表の左列（担当者名）から読み取ります。"
)

if "rows" not in st.session_state:
    st.session_state.rows = []  # type: ignore[attr-defined]

def _parse_name_list(text: str) -> set[str]:
    """1行1名、またはカンマ区切り。空行は無視。"""
    out: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "," in line:
            for p in line.split(","):
                if p.strip():
                    out.add(p.strip())
        else:
            out.add(line)
    return out


with st.sidebar:
    st.caption(f"アプリ版 **{_read_app_version()}**（表示が古いときは Cloud の「Reboot」または再デプロイ）")
    st.subheader("取り込み")
    uploads = st.file_uploader(
        "PDF / CSV / Excel を選択（複数可）",
        type=["pdf", "csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )
    parse_report = st.toggle("担当別訪問件数PDFとして集計する", value=True)
    show_formula = st.toggle("分数合計と計算式も表示する", value=False)

    st.divider()
    with st.expander("表示の絞り込み（任意）", expanded=False):
        st.caption("通常は空のままで問題ありません。一覧を絞りたいときだけ使います。")
        exclude_text = st.text_area(
            "集計から除外する名前",
            height=80,
            placeholder="1行に1名、またはカンマ区切り",
            help="表示から外したい行の担当者名。空なら全員表示。",
            key="exclude_names_area",
        )
        include_text = st.text_area(
            "集計に含める担当者のみ",
            height=64,
            placeholder="空欄なら全員。絞るときは1行に1名",
            help="空欄のときはフィルタしません。",
            key="include_only_area",
        )

    if st.button("取り込み実行", type="primary", disabled=not uploads):
        if parse_report and uploads and any(u.name.lower().endswith(".pdf") for u in uploads):
            # 1つ目のPDFだけを集計対象にする（複数PDF対応は後で拡張可能）
            pdf_u = next(u for u in uploads if u.name.lower().endswith(".pdf"))
            pdf_bytes = pdf_u.getvalue()
            st.session_state.report_df = summarize_monthly_visit_hours_from_report_pdf(pdf_bytes)  # type: ignore[attr-defined]
            # 表の key を変えて Streamlit クライアント側の列ソート状態をリセット（PDF 順に戻す）
            st.session_state.report_table_key = st.session_state.get("report_table_key", 0) + 1
            st.success("担当別の集計を作成しました")
        else:
            new_rows: list[VisitRow] = []
            for u in uploads or []:
                new_rows.extend(load_file_to_rows(u))
            st.session_state.rows = st.session_state.rows + new_rows  # type: ignore[attr-defined]
            st.success(f"{len(new_rows)} 件取り込みました")

    if st.button("全クリア"):
        st.session_state.rows = []  # type: ignore[attr-defined]
        if "report_df" in st.session_state:
            del st.session_state["report_df"]
        if "report_table_key" in st.session_state:
            del st.session_state["report_table_key"]


rows: list[VisitRow] = st.session_state.rows  # type: ignore[assignment]
df = rows_to_df(rows) if rows else pd.DataFrame(columns=["date", "staff", "place", "category", "source", "raw"])

if "report_df" in st.session_state and isinstance(st.session_state["report_df"], pd.DataFrame):
    st.subheader("担当別 集計結果（分→時間）")
    rdf: pd.DataFrame = st.session_state["report_df"]
    if rdf.empty:
        st.warning("集計結果が空でした。PDF形式が想定と違う可能性があります。")
    else:
        ex = _parse_name_list(exclude_text)
        inc = _parse_name_list(include_text)
        if "_pdf_order" not in rdf.columns:
            st.warning(
                "この集計データには **並び順用の情報（_pdf_order）** がありません。"
                " コード更新前のセッションの可能性があります。**PDF をもう一度「取り込み実行」** してください。"
            )
        show = _apply_staff_filter(rdf.copy(), ex, inc)
        show = _sort_report_df_by_pdf_order(show)
        show = add_revenue_columns(show, SUPPORT_RATIO_FOR_FEES)
        show = add_medical_insurance_columns(show)
        show = _reorder_report_columns_for_display(show)
        drop_cols = ["_職種", "_pdf_order"]
        if not show_formula:
            drop_cols += [
                "_分数合計",
                "計算式",
                "_vis3",
                "_p60",
                "_vis2_s",
                "_vis3_s",
                "_vis4_s",
                "_p20_s",
                "_p40_s",
                "_p60_s",
                "_vis2_c",
                "_vis3_c",
                "_vis4_c",
                "_p20_c",
                "_p40_c",
                "_p60_c",
                "_other_s",
                "_other_c",
                "_record_s",
                "_record_c",
                "_pricing_split",
            ]
        show = show.drop(columns=[c for c in drop_cols if c in show.columns])
        c1, c2 = st.columns([4, 1])
        with c1:
            if "他" in show.columns or "記録" in show.columns:
                st.caption(
                    "列「他」「記録」は帳票サマリーから拾った回数です（"
                    "**1回あたり60分** として「件数」に含みます）。90 の右隣に並びます。"
                )
            st.caption(
                "**行の並びは PDF の担当者ブロック先頭順です。** "
                "表の **列見出しをクリックするとブラウザが並べ替え**（見た目が PDF とずれます）。"
                "下のボタンか、もう一度「取り込み実行」で PDF 順に戻せます。"
            )
        with c2:
            if st.button("表をPDF順に戻す", key="reset_visit_report_sort", use_container_width=True):
                st.session_state.report_table_key = st.session_state.get("report_table_key", 0) + 1
                st.rerun()
        _cols = list(show.columns)
        _tbl_key = int(st.session_state.get("report_table_key", 0))
        st.dataframe(
            show,
            use_container_width=True,
            hide_index=True,
            height=520,
            column_order=_cols,
            column_config=_report_visit_table_column_config(show),
            key=f"visit_report_{_tbl_key}",
        )
        csv_for_dl = show.rename(
            columns={k: v for k, v in REPORT_SUMMARY_EXTRA_COLUMN_LABELS.items() if k in show.columns}
        )
        out = csv_for_dl.to_csv(index=False).encode("utf-8-sig")
        st.download_button("集計CSVダウンロード", data=out, file_name="monthly_visit_hours.csv", mime="text/csv")

        st.divider()
        st.subheader("ダッシュボード")
        rdf_dash = _sort_report_df_by_pdf_order(_apply_staff_filter(rdf.copy(), ex, inc))
        _render_report_dashboard_section(rdf_dash)

elif df.empty:
    st.info("左のサイドバーからファイルを取り込んでください。")
else:
    st.subheader("明細")
    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "date": st.column_config.TextColumn("日付"),
            "staff": st.column_config.TextColumn("担当"),
            "place": st.column_config.TextColumn("訪問先"),
            "category": st.column_config.TextColumn("カテゴリ"),
            "source": st.column_config.TextColumn("ソース", disabled=True),
            "raw": st.column_config.TextColumn("元テキスト/備考"),
        },
        hide_index=True,
    )

    st.session_state.rows = [
        VisitRow(
            date=str(r.get("date", "")),
            staff=str(r.get("staff", "")),
            place=str(r.get("place", "")),
            category=str(r.get("category", "")),
            source=str(r.get("source", "")),
            raw=str(r.get("raw", "")),
        )
        for _, r in edited.iterrows()
    ]

    st.divider()
    st.subheader("カテゴリ別サマリー")
    df2 = rows_to_df(st.session_state.rows)  # type: ignore[attr-defined]
    total = len(df2)
    st.metric("件数", f"{total:,}")
    by_cat = (
        df2.groupby("category", dropna=False)
        .size()
        .reset_index(name="件数")
        .sort_values(["件数", "category"], ascending=[False, True])
    )
    st.dataframe(by_cat, use_container_width=True, hide_index=True)
    csv = df2.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSVダウンロード", data=csv, file_name="visits.csv", mime="text/csv")

