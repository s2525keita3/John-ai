from __future__ import annotations

import io
import re
from datetime import date
from typing import Iterable

import pandas as pd
import pdfplumber

from medical_insurance_calc import MedicalVisitEvent, compute_medical_insurance_fees

def _normalize_text(s: str) -> str:
    s = s.replace("\u3000", " ").strip()
    s = re.sub(r"[ \t]+", " ", s)
    return s


def _extract_full_text_from_pdf(file_bytes: bytes) -> str:
    """
    まず pdfplumber を優先（今回のPDFはこれが一番安定して日本語が取れる）し、
    取れなければ PyMuPDF → pypdfium2 の順でフォールバック。
    """
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
        text = "\n".join(pages)
        if text.strip():
            return text
    except Exception:
        pass

    try:
        import fitz  # PyMuPDF  # type: ignore

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = [doc.load_page(i).get_text("text") for i in range(doc.page_count)]
        doc.close()
        text = "\n".join(pages)
        if text.strip():
            return text
    except Exception:
        pass

    try:
        import pypdfium2 as pdfium  # type: ignore

        doc = pdfium.PdfDocument(file_bytes)
        out_pages: list[str] = []
        for i in range(len(doc)):
            page = doc[i]
            textpage = page.get_textpage()
            out_pages.append(textpage.get_text_range() or "")
            textpage.close()
            page.close()
        doc.close()
        text = "\n".join(out_pages)
        if text.strip():
            return text
    except Exception:
        pass

    # 最終フォールバック（ここまで来たら空でも返す）
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
        return "\n".join(pages)
    except Exception:
        return ""


def _canonical_staff_name(name: str) -> str:
    name = _normalize_text(name)
    # 先頭に数字が混ざった誤抽出を除去（例: "51 石田"）
    name = re.sub(r"^\d+\s+", "", name)
    return name


def _count同行_from_text(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        line = _normalize_text(line)
        if not (line.startswith("副)2回目訪問") or re.match(r"^.{0,3}\)\s*2", line)):
            continue
        parts = [p for p in re.split(r"\s+", line) if p]
        if len(parts) < 3:
            continue
        staff = _canonical_staff_name(" ".join(parts[-2:]))
        counts[staff] = counts.get(staff, 0) + 1
    return counts


def _iter_staff_blocks(text: str) -> Iterable[tuple[str, str]]:
    # pdfplumber/pdfminer だと文字化けして「担当者名」が別表記になる場合がある
    header = "担当者名" if "担当者名" in text else ("�S���Җ�" if "�S���Җ�" in text else "担当者名")
    chunks = text.split(header)
    for chunk in chunks[1:]:
        lines = [l for l in chunk.splitlines() if _normalize_text(l)]
        staff = ""
        for l in lines:
            nl = _normalize_text(l)
            if nl.startswith(("利用者名", "日付", "No", "【令和", "ページ：", "--", "副)2回目訪問")):
                continue

            # 例: "佐々木 勇磨 2 09：30～10：00 訪問看護2 ..."
            m = re.match(r"^\d+\s+([^\s\d]+)\s+([^\s\d]+)\s+\d{1,2}\s+\d{1,2}[：�F]\d{2}", nl)
            if m:
                staff = _canonical_staff_name(f"{m.group(1)} {m.group(2)}")
                break

            m = re.match(r"^([^\s\d]+)\s+([^\s\d]+)\s+\d{1,2}\s+\d{1,2}[：�F]\d{2}", nl)
            if m:
                staff = _canonical_staff_name(f"{m.group(1)} {m.group(2)}")
                break

            parts = [p for p in re.split(r"\s+", nl) if p]
            if len(parts) >= 2:
                if re.fullmatch(r"\d+", parts[0]) or parts[0].endswith(("回", "日", "分")):
                    continue
                if re.fullmatch(r"\d+", parts[1]) or parts[1].endswith(("回", "日", "分")):
                    continue
                staff = _canonical_staff_name(f"{parts[0]} {parts[1]}")
                break

        if staff:
            yield staff, "\n".join(lines)


def _extract_medical_count_from_block(block_text: str) -> int:
    """
    サマリー欄の「介護○回 / 医療○回 / ○日 / ○日 / ○分 / ○分」から医療の回数（2行目の○回）を取る。
    PDFの改行・空白の差で従来パターンが一致しないことがあるので複数手を試す。
    """
    t = block_text.replace("\r\n", "\n").replace("\r", "\n")

    # 1) 標準: 回→回→日→日→分→分（ブロック先頭に改行が無くてもよい）
    m = re.search(
        r"(\d+)回\s*\n(\d+)回\s*\n(\d+)日\s*\n(\d+)日\s*\n(\d+)分\s*\n(\d+)分",
        t,
    )
    if m:
        return int(m.group(2))

    # 2) タブ区切り・行末空白などゆるい版
    m = re.search(
        r"(\d+)回\s*[\n\t]+(\d+)回\s*[\n\t]+(\d+)日\s*[\n\t]+(\d+)日\s*[\n\t]+(\d+)分\s*[\n\t]+(\d+)分",
        t,
    )
    if m:
        return int(m.group(2))

    # 3) 「医療」の直後・次行に ○回（表によってはこちらだけ取れる）
    m = re.search(r"医療[^\d\n]*\n\s*(\d+)回", t)
    if m:
        return int(m.group(1))
    m = re.search(r"医療\s*(\d+)回", t)
    if m:
        return int(m.group(1))

    # 4) 下段「○分」「○分」の2行目が医療側の分数 → 60分/回で回数に換算（最後の手段）
    m = re.search(r"(\d+)分\s*\n\s*(\d+)分\s*(?:\n|$)", t)
    if m:
        med_min = int(m.group(2))
        if med_min > 0 and med_min % 60 == 0:
            return med_min // 60

    return 0


def _count_occurrences(block_text: str, needle: str) -> int:
    return len(re.findall(re.escape(needle), block_text))


def _parse_date_from_line(line: str) -> date | None:
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", line)
    if m:
        ry, mo, da = map(int, m.groups())
        y = 2018 + ry
        try:
            return date(y, mo, da)
        except ValueError:
            return None
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", line)
    if m:
        y, mo, da = map(int, m.groups())
        try:
            return date(y, mo, da)
        except ValueError:
            return None
    m = re.search(r"R\s*(\d+)\s*[\.．]\s*(\d+)\s*[\.．]\s*(\d+)", line, flags=re.IGNORECASE)
    if m:
        ry, mo, da = map(int, m.groups())
        y = 2018 + ry
        try:
            return date(y, mo, da)
        except ValueError:
            return None
    return None


def _line_looks_like_medical_visit_detail(line: str) -> bool:
    """明細行: 医療区分かつ日時らしきパターンがある行。"""
    nl = _normalize_text(line)
    if "医療" not in nl:
        return False
    if re.search(r"\d{1,2}\s+\d{1,2}\s*[：:�F]\s*\d{2}", nl):
        return True
    if re.search(r"\d{1,2}\s*[：:�F]\s*\d{2}", nl) and ("訪問" in nl or "～" in nl or "~" in nl):
        return True
    if "訪問" in nl and "医療" in nl:
        return True
    return False


def _parse_patient_key_from_line(line: str) -> str:
    s = _normalize_text(line)
    m = re.match(r"^\d+\s+([^\s\d]+)\s+([^\s\d]+)\s+", s)
    if m:
        return _canonical_staff_name(f"{m.group(1)} {m.group(2)}")
    m = re.match(r"^([^\s\d]+)\s+([^\s\d]+)\s+\d{1,2}\s+\d{1,2}\s*[：:�F]", s)
    if m:
        return _canonical_staff_name(f"{m.group(1)} {m.group(2)}")
    return "不明"


def extract_medical_visit_events(full_text: str) -> list[MedicalVisitEvent]:
    """PDF全文から「医療」明細行を検出し、日付・利用者・担当を付与する。"""
    out: list[MedicalVisitEvent] = []
    line_no = 0
    for staff, block in _iter_staff_blocks(full_text):
        for line in block.splitlines():
            line_no += 1
            nl = _normalize_text(line)
            if not _line_looks_like_medical_visit_detail(nl):
                continue
            d = _parse_date_from_line(nl)
            if not d:
                continue
            pk = _parse_patient_key_from_line(nl)
            out.append(
                MedicalVisitEvent(
                    staff=staff,
                    visit_date=d,
                    patient_key=pk,
                    line_index=line_no,
                    raw_line=nl[:240],
                )
            )
    return out


def build_medical_insurance_bundle(file_bytes: bytes, report_df: pd.DataFrame | None = None) -> dict:
    """
    医療保険の概算（10割）と明細。report_df があればサマリー医療件数と突き合わせて注意を付与。
    """
    full_text = _extract_full_text_from_pdf(file_bytes)
    events = extract_medical_visit_events(full_text)
    result = compute_medical_insurance_fees(events)
    agg_med = 0
    if report_df is not None and not report_df.empty and "医療" in report_df.columns:
        agg_med = int(report_df["医療"].sum())

    evc = result.get("visit_count", len(events))
    w = list(result.get("warnings", []))
    if agg_med > 0 and evc == 0:
        w.append(
            f"サマリーの医療は合計 {agg_med} 回ですが、明細行（医療＋日付）からは 0 件検出できませんでした。"
            " PDFのレイアウトや文字化けの可能性があります。"
        )
    elif agg_med > 0 and evc != agg_med:
        w.append(
            f"サマリー医療 {agg_med} 回に対し、明細から検出した訪問は {evc} 件です。取りこぼしがある場合は金額を確認してください。"
        )
    result["warnings"] = w
    result["agg_medical_count"] = agg_med
    result["parsed_visit_count"] = evc
    return result


def summarize_report_pdf(file_bytes: bytes) -> pd.DataFrame:
    """
    出力列（画像の形式）:
      担当者, 20, 30, 40, 60, 90, 他, 記録, 医療, 同行, 件数
      「他」「記録」はサマリー（例: 他: 1回）から読み、各1回＝60分として分数に加算する。

    件数は「分数合計 / 60（時間）」を小数1桁で表示。
    療法士の P40（列「40」）は 0.6時間/回（36分相当）で計算する。

    列「60」は帳票上で訪問看護3（vis3）と療法P60の両方に使われる。
    P20/P40 が無く vis があるのに vis3==P60 だけ一致する場合は、訪3の重複とみなし P60 を 0 にする。
    訪問看護と療法の件数が両方ある担当は分数・売上を合算し、職種は「看護師・療法士」。
    """
    full_text = _extract_full_text_from_pdf(file_bytes)
    同行_map = _count同行_from_text(full_text)

    def _pick_count(label_regex: str, text: str) -> int:
        m = re.search(label_regex, text, flags=re.MULTILINE)
        return int(m.group(1)) if m else 0

    def _extract_summary_counts(block_text: str) -> dict[str, int]:
        # 「訪2: 21回」「P40: 15回」等のサマリーから読む（ページ明細の出現回数は使わない）
        t = block_text
        return {
            "vis2": _pick_count(r"(?:訪|�K)2[:：]\s*(\d+)回", t),
            "vis3": _pick_count(r"(?:訪|�K)3[:：]\s*(\d+)回", t),
            "vis4": _pick_count(r"(?:訪|�K)4[:：]\s*(\d+)回", t),
            "p20": _pick_count(r"P20[:：]\s*(\d+)回", t),
            "p40": _pick_count(r"P40[:：]\s*(\d+)回", t),
            "p60": _pick_count(r"P60[:：]\s*(\d+)回", t),
            "other": _pick_count(r"他[:：]\s*(\d+)回", t),
            "record": _pick_count(r"記録[:：]\s*(\d+)回", t),
        }

    def _zero_counts() -> dict[str, int]:
        return {k: 0 for k in ("vis2", "vis3", "vis4", "p20", "p40", "p60", "other", "record")}

    def _extract_support_care_counts(block_text: str) -> tuple[dict[str, int], dict[str, int], bool]:
        """
        支援（予防・介護予防）と介護のサマリーを分離して読む。
        - 行が「介護」のみの行で区切る：その上＝支援エリア（予防含む）、その下＝介護エリア。
        - 「介護」見出しが無く「支援」または「介護予防」見出しのみ → ブロック全体を支援。
        - どれも無い → 従来どおりすべて介護。
        """
        t = block_text
        m_sep = re.search(r"(?m)^介護\s*$", t)
        if m_sep:
            sup_part = t[: m_sep.start()]
            car_part = t[m_sep.end() :]
            return _extract_summary_counts(sup_part), _extract_summary_counts(car_part), True

        if (
            re.search(r"(?m)^支援\s*$", t)
            or re.search(r"(?m)^介護予防\s*$", t)
            or re.search(r"(?m)^予防\s*$", t)
        ) and not re.search(r"(?m)^介護\s*$", t):
            return _extract_summary_counts(t), _zero_counts(), True

        return _zero_counts(), _extract_summary_counts(t), False

    agg: dict[str, dict[str, int]] = {}
    # PDF 上で「担当者名」ブロックが先に現れた順（上→下）を保持する
    staff_pdf_order: dict[str, int] = {}
    _next_pdf_order = 0
    for staff, block in _iter_staff_blocks(full_text):
        if staff not in staff_pdf_order:
            staff_pdf_order[staff] = _next_pdf_order
            _next_pdf_order += 1
        if staff not in agg:
            agg[staff] = {
                "vis2_s": 0,
                "vis3_s": 0,
                "vis4_s": 0,
                "p20_s": 0,
                "p40_s": 0,
                "p60_s": 0,
                "vis2_c": 0,
                "vis3_c": 0,
                "vis4_c": 0,
                "p20_c": 0,
                "p40_c": 0,
                "p60_c": 0,
                "split_any": False,
                "medical": 0,
                "同行": 0,
                "other_s": 0,
                "other_c": 0,
                "record_s": 0,
                "record_c": 0,
            }

        s, c, used_split = _extract_support_care_counts(block)
        for k in ("vis2", "vis3", "vis4", "p20", "p40", "p60", "other", "record"):
            agg[staff][f"{k}_s"] += s[k]
            agg[staff][f"{k}_c"] += c[k]
        agg[staff]["split_any"] = bool(agg[staff]["split_any"] or used_split)

        agg[staff]["medical"] += _extract_medical_count_from_block(block)

        # 同行は「2回目訪問」表記をブロック内から直接数える（末尾一覧が読めないケースの救済）
        agg[staff]["同行"] += block.count("2回目訪問") + block.count("2��ږK��")

    rows: list[dict[str, object]] = []
    for staff, a in agg.items():
        vis2_s = a["vis2_s"]
        vis3_s = a["vis3_s"]
        vis4_s = a["vis4_s"]
        p20_s = a["p20_s"]
        p40_s = a["p40_s"]
        p60_s = a["p60_s"]
        vis2_c = a["vis2_c"]
        vis3_c = a["vis3_c"]
        vis4_c = a["vis4_c"]
        p20_c = a["p20_c"]
        p40_c = a["p40_c"]
        p60_c = a["p60_c"]
        other_s = a["other_s"]
        other_c = a["other_c"]
        record_s = a["record_s"]
        record_c = a["record_c"]

        vis2 = vis2_s + vis2_c
        vis3 = vis3_s + vis3_c
        vis4 = vis4_s + vis4_c
        p20 = p20_s + p20_c
        p40 = p40_s + p40_c
        p60 = p60_s + p60_c
        other = other_s + other_c
        record = record_s + record_c
        medical = a["medical"]
        同行 = max(a.get("同行", 0), 同行_map.get(staff, 0))

        # 列「60」の重複（訪3 と P60 が同じ数値で二重計上された場合）
        if p20 == 0 and p40 == 0 and p60 > 0 and (vis2 + vis3 + vis4) > 0 and vis3 == p60:
            p60 = 0
            p60_s = 0
            p60_c = 0

        has_vis = (vis2 + vis3 + vis4) > 0
        has_pt = (p20 + p40 + p60) > 0

        extra_60 = (other + record) * 60
        if has_vis and has_pt:
            minutes_n = vis2 * 30 + vis3 * 60 + vis4 * 90
            minutes_pt = p20 * 20 + p40 * 36 + p60 * 60
            minutes = minutes_n + minutes_pt + medical * 60 - 同行 * 60 + extra_60
            formula = (
                f"(30*{vis2}+60*{vis3}+90*{vis4})+(20*{p20}+36*{p40}+60*{p60})"
                f"+60*{medical}-60*{同行}+60*{other}+60*{record}"
            )
            role = "看護師・療法士"
        elif has_pt:
            minutes = p20 * 20 + p40 * 36 + p60 * 60 + medical * 60 - 同行 * 60 + extra_60
            formula = f"20*{p20}+36*{p40}+60*{p60}+60*{medical}-60*{同行}+60*{other}+60*{record}"
            role = "療法士"
        elif has_vis:
            minutes = vis2 * 30 + vis3 * 60 + vis4 * 90 + medical * 60 - 同行 * 60 + extra_60
            formula = f"30*{vis2}+60*{vis3}+90*{vis4}+60*{medical}-60*{同行}+60*{other}+60*{record}"
            role = "看護師"
        else:
            minutes = medical * 60 - 同行 * 60 + extra_60
            formula = f"60*{medical}-60*{同行}+60*{other}+60*{record}"
            role = "—"

        hours = float(minutes) / 60.0

        c20 = p20 if has_pt else 0
        c30 = vis2 if has_vis else 0
        c40 = p40 if has_pt else 0
        if has_vis:
            c60 = vis3
        else:
            c60 = p60
        c90 = vis4 if has_vis else 0

        rows.append(
            {
                "担当者": staff,
                "20": int(c20),
                "30": int(c30),
                "40": int(c40),
                "60": int(c60),
                "90": int(c90),
                "他": int(other),
                "記録": int(record),
                "医療": int(medical),
                "同行": int(同行),
                "件数": round(hours, 1),
                "_職種": role,
                "_分数合計": int(minutes),
                "計算式": formula,
                "_vis3": int(vis3),
                "_p60": int(p60),
                "_vis2_s": int(vis2_s),
                "_vis3_s": int(vis3_s),
                "_vis4_s": int(vis4_s),
                "_p20_s": int(p20_s),
                "_p40_s": int(p40_s),
                "_p60_s": int(p60_s),
                "_vis2_c": int(vis2_c),
                "_vis3_c": int(vis3_c),
                "_vis4_c": int(vis4_c),
                "_p20_c": int(p20_c),
                "_p40_c": int(p40_c),
                "_p60_c": int(p60_c),
                "_other_s": int(other_s),
                "_other_c": int(other_c),
                "_record_s": int(record_s),
                "_record_c": int(record_c),
                "_pricing_split": bool(a.get("split_any")),
                "_pdf_order": int(staff_pdf_order.get(staff, 0)),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("_pdf_order", ascending=True).drop(columns=["_pdf_order"])
    return df

