"""
横浜信用金庫 通帳・入出金一覧のスキャンPDF（画像のみ）を OCR して取り込む。

方針:
- テキストレイヤが十分ある場合はそれを優先（コピー可能なPDF）。
- 画像のみの場合は OCR（Tesseract 優先、無ければ EasyOCR）。
- 日付・金額が一意に解釈できない行は「不明」または「要確認」とし、
  誤取り込みを避ける（ユーザー要望）。
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
import pandas as pd

# 日付（YY/MM/DD）— 厳密
DATE_STRICT = re.compile(r"(?P<y>\d{2})/(?P<m>\d{2})/(?P<d>\d{2})")
# OCR ゆれ（要確認扱い）
DATE_LOOSE = re.compile(
    r"(?P<y>\d{1,2})[\./．](?P<m>\d{1,2})[\./．](?P<d>\d{1,2})"
)
# 横浜スキャンで「25.02.27」が「108.02,27」「208.02.27」のように読まれる（行番号+08→25）
_PASSBOOK_YEAR_SUFFIX_08 = re.compile(
    r"^(?P<prefix>\d{0,3})(?P<yy>08)(?P<sep1>[\./,．])(?P<m>\d{1,2})(?P<sep2>[\./,．])(?P<d>\d{1,2})$"
)
# カンマ区切り・桁数可変（手書き・OCRゆれ対応）
AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{1,10}")

# Tesseract 既定の image_to_data は通帳でノイズ（丸囲み数字等）が多い → 品質が悪ければ EasyOCR に切替
_TESS_MIN_MEAN_CONF = 0.38
_TESS_MAX_CIRCLED_RATIO = 0.08


def _normalize_ocr_text(s: str) -> str:
    """丸囲み・全角数字などを半角数字へ寄せ、日付・金額抽出を安定させる。"""
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if o in (0x24EA, 0x24FF, 0x3007):  # ⓪ 〇
            out.append("0")
        elif 0x2460 <= o <= 0x2468:  # ①-⑨
            out.append(str(o - 0x2460 + 1))
        elif 0x2469 <= o <= 0x2473:  # ⑩-⑳
            out.append(str(o - 0x2469 + 10))
        elif 0x2776 <= o <= 0x277E:  # ❶-❾
            out.append(str(o - 0x2776 + 1))
        elif 0xFF10 <= o <= 0xFF19:  # 全角 ０-９
            out.append(chr(o - 0xFF10 + ord("0")))
        else:
            out.append(ch)
    return "".join(out)


def _circled_noise_ratio(s: str) -> float:
    n = len(s)
    if n == 0:
        return 0.0
    bad = 0
    for ch in s:
        o = ord(ch)
        if (
            0x2460 <= o <= 0x2473
            or o in (0x24EA, 0x24FF)
            or 0x2776 <= o <= 0x277E
        ):
            bad += 1
    return bad / n


def _normalize_tokens(tokens: list[OcrToken]) -> list[OcrToken]:
    return [
        OcrToken(t.x, t.y, _normalize_ocr_text(t.text), t.conf) for t in tokens
    ]


def _binarize_for_tesseract(rgb: np.ndarray) -> np.ndarray:
    """Tesseract はコントラストの高い二値画像の方が表形式の数字を拾いやすいことが多い。"""
    try:
        import cv2  # type: ignore

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        th = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            35,
            12,
        )
        return cv2.cvtColor(th, cv2.COLOR_GRAY2RGB)
    except Exception:
        return rgb


def _tesseract_tokens_quality(tokens: list[OcrToken]) -> float:
    if not tokens:
        return 0.0
    confs = [t.conf for t in tokens if t.conf >= 0]
    mean_c = sum(confs) / len(confs) if confs else 0.0
    joined = "".join(t.text for t in tokens)
    pen = _circled_noise_ratio(joined)
    return max(0.0, mean_c - pen * 2.0)


def _should_fallback_easyocr(ts: list[OcrToken] | None) -> bool:
    if not ts:
        return True
    confs = [t.conf for t in ts if t.conf >= 0]
    mean_c = sum(confs) / len(confs) if confs else 0.0
    joined = "".join(t.text for t in ts)
    circ = _circled_noise_ratio(joined)
    return mean_c < _TESS_MIN_MEAN_CONF or circ > _TESS_MAX_CIRCLED_RATIO


@dataclass
class OcrToken:
    x: float
    y: float
    text: str
    conf: float


def _page_to_rgb(page: fitz.Page, dpi: int = 300) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        arr = arr[:, :, :3]
    return arr


def _enhance_scan_image(arr: np.ndarray) -> np.ndarray:
    """薄いスキャン向けにコントラストを上げる（OpenCV があれば使用）。"""
    try:
        import cv2  # type: ignore

        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
        sharp = cv2.addWeighted(gray, 1.4, blur, -0.4, 0)
        rgb = cv2.cvtColor(sharp, cv2.COLOR_GRAY2RGB)
        return rgb
    except Exception:
        return arr


def _try_embedded_text(doc: fitz.Document) -> str:
    parts: list[str] = []
    for p in doc:
        parts.append(p.get_text())
    return "\n".join(parts)


def _project_tessdata_prefix() -> Path | None:
    """リポジトリ同梱の tessdata（jpn）があればそのパス。TESSDATA_PREFIX に使う。"""
    td = Path(__file__).resolve().parent / "tessdata"
    if (td / "jpn.traineddata").is_file():
        return td
    return None


def _ensure_tesseract_executable() -> bool:
    """
    Tesseract が PATH に無い場合でも、環境変数 TESSERACT_CMD または
    Windows 既定インストール先（UB-Mannheim 等）を試す。
    """
    try:
        import pytesseract
    except ImportError:
        return False
    if shutil.which("tesseract"):
        return True
    candidates: list[str] = []
    env = os.environ.get("TESSERACT_CMD", "").strip()
    if env:
        candidates.append(env)
    candidates.extend(
        (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        )
    )
    for p in candidates:
        if p and Path(p).is_file():
            pytesseract.pytesseract.tesseract_cmd = p
            return True
    return False


def _ocr_tesseract_once(
    img: np.ndarray,
    *,
    lang: str = "jpn",
    config: str = "",
) -> list[OcrToken] | None:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None

    if not _ensure_tesseract_executable():
        return None

    proj_td = _project_tessdata_prefix()
    if proj_td is not None:
        os.environ["TESSDATA_PREFIX"] = str(proj_td)

    pil = Image.fromarray(img)
    data = pytesseract.image_to_data(
        pil,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.DICT,
    )
    tokens: list[OcrToken] = []
    n = len(data["text"])
    for i in range(n):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0:
            conf = 0.0
        tokens.append(
            OcrToken(
                float(data["left"][i]),
                float(data["top"][i]),
                t,
                conf / 100.0,
            )
        )
    return tokens


def _ocr_tesseract_best(img: np.ndarray) -> list[OcrToken] | None:
    """
    複数の前処理・PSM で試し、品質スコアが最も高い結果を返す。
    通帳スキャンでは --psm 6（均一ブロック）が安定しやすい。
    """
    bin_img = _binarize_for_tesseract(img)
    variants: list[tuple[np.ndarray, str, str]] = [
        (img, "jpn", r"--oem 1 --psm 6"),
        (bin_img, "jpn", r"--oem 1 --psm 6"),
        (img, "jpn+jpn_vert+eng", r"--oem 1 --psm 6"),
        (bin_img, "jpn+jpn_vert+eng", r"--oem 1 --psm 6"),
        (img, "jpn", r"--oem 1 --psm 4"),
        (bin_img, "jpn", r"--oem 1 --psm 4"),
    ]
    best: list[OcrToken] | None = None
    best_score = -1.0
    for im, lang, cfg in variants:
        try:
            ts = _ocr_tesseract_once(im, lang=lang, config=cfg)
        except Exception:
            continue
        if not ts:
            continue
        sc = _tesseract_tokens_quality(ts)
        if sc > best_score:
            best_score = sc
            best = ts
    return best


def _ocr_easyocr(img: np.ndarray) -> list[OcrToken]:
    import easyocr

    reader = easyocr.Reader(["ja", "en"], gpu=False, verbose=False)
    res = reader.readtext(img)
    tokens: list[OcrToken] = []
    for box, text, conf in res:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        tokens.append(OcrToken(min(xs), sum(ys) / len(ys), text.strip(), float(conf)))
    return tokens


def _cluster_rows(tokens: list[OcrToken], y_tol: float = 20.0) -> list[list[OcrToken]]:
    if not tokens:
        return []
    by_y = sorted(tokens, key=lambda t: (t.y, t.x))
    rows: list[list[OcrToken]] = []
    cur: list[OcrToken] = []
    for t in by_y:
        if not cur:
            cur.append(t)
            continue
        y_avg = sum(x.y for x in cur) / len(cur)
        if abs(t.y - y_avg) <= y_tol:
            cur.append(t)
        else:
            rows.append(sorted(cur, key=lambda x: x.x))
            cur = [t]
    if cur:
        rows.append(sorted(cur, key=lambda x: x.x))
    return rows


def _parse_amount(s: str) -> float | None:
    s = str(s).replace(",", "").replace("，", "").strip()
    if not s.isdigit():
        return None
    return float(int(s))


def _token_is_pure_amount(text: str) -> bool:
    t = text.replace(",", "").replace("，", "").strip()
    return t.isdigit() and len(t) >= 1


def _token_has_date(text: str) -> bool:
    return DATE_STRICT.search(text.replace(" ", "").replace("　", "")) is not None


def _fix_passbook_yy08_token(token: str) -> str:
    """
    「108.02,27」「1008.03,25」形式で YY が 08 と誤認されたものを 25 に直す（2025年台の通帳想定）。
    「2008」単体の西暦4桁は触らない（トークン全体が 2008 のとき）。
    """
    t = token.strip().replace(" ", "").replace("　", "")
    if t == "2008":
        return t
    m = _PASSBOOK_YEAR_SUFFIX_08.match(t.replace("．", "."))
    if not m:
        return token
    # 西暦 2008 年（4桁で 2008）を誤爆しないよう、末尾が ...08 で全体が 2008 のパターンは除外済み
    yy = m.group("yy")
    if yy != "08":
        return token
    # prefix が長すぎる（例: 200 + 08）は西暦 2008 年などの可能性で触らない
    prefix = m.group("prefix") or ""
    if len(prefix) >= 3:
        return token
    sep1, sep2 = m.group("sep1"), m.group("sep2")
    mo, d = m.group("m"), m.group("d")
    # 行番号(1,2,…10)+「08」が「25」の誤認のため、年は 25 のみにする
    # 以降のパースを単純にするため区切りは / に統一
    mo_i, d_i = int(mo), int(d)
    return f"25/{mo_i:02d}/{d_i:02d}"


def _normalize_one_token_for_date(raw: str) -> str:
    """空白区切り1トークン: 108→25 補正と YY.MM.DD → YY/MM/DD（金額トークンはそのまま）。"""
    t0 = raw.strip()
    if not t0:
        return raw
    t = _fix_passbook_yy08_token(t0)
    ts = t.replace("．", ".").strip()
    # 日付のみのトークン（*3,630 等は除外）
    if ts.startswith("*") or ts.startswith("#"):
        return t
    if re.match(r"^\d{2}[\./,]\d{1,2}[\./,]\d{1,2}$", ts):
        ts = ts.replace(".", "/").replace(",", "/")
        a, b, c = ts.split("/")
        return f"{int(a):02d}/{int(b):02d}/{int(c):02d}"
    return t


def _normalize_line_for_date(line: str) -> str:
    """日付抽出用にトークン単位で区切りを正す（金額のカンマは別トークンなら維持）。"""
    parts: list[str] = []
    for raw in re.split(r"(\s+)", line):
        if raw.strip() == "":
            parts.append(raw)
            continue
        parts.append(_normalize_one_token_for_date(raw))
    return "".join(parts)


def _token_looks_like_passbook_date(text: str) -> bool:
    """日付トークン（金額抽出から除外）。"""
    t = text.strip().replace("．", ".").replace("，", ",")
    if _PASSBOOK_YEAR_SUFFIX_08.match(t):
        return True
    if re.match(r"^\d{1,4}[\./,]\d{1,2}[\./,]\d{1,2}", t):
        return True
    return False


def _extract_date(line: str) -> tuple[str | None, str]:
    """
    戻り値: (正規化日付文字列 or None, ステータス理由補助)
    OCR で「25.02.27」「25．02．27」等になる場合もスラッシュに寄せて照合。
    金額のカンマを壊さないよう、トークン単位で区切りを直してから結合する。
    """
    line_compact = _normalize_line_for_date(line)
    line_compact = line_compact.replace(" ", "").replace("　", "")
    m = re.search(
        r"(?P<y>\d{2,4})/(?P<m>\d{1,2})/(?P<d>\d{1,2})",
        line_compact,
    )
    if m:
        y_raw = int(m.group("y"))
        mo, d = int(m.group("m")), int(m.group("d"))
        if y_raw >= 100:
            y = y_raw % 100
        else:
            y = y_raw
        if y < 50:
            full_y = 2000 + y
        else:
            full_y = 1900 + y
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{full_y:04d}-{mo:02d}-{d:02d}", "strict"
    m2 = DATE_LOOSE.search(line_compact)
    if m2:
        return None, "loose_date"
    return None, "no_date"


def _classify_row(tokens: list[OcrToken]) -> dict:
    """
    横浜信用金庫通帳スキャン想定（左→右）:
    年月日 | お取引内容・お支払先 | お支払金額 | お預かり金額 | 残高
    金額は左から順に お支払(出金)・お預かり(入金)・残高。
    """
    texts = [t.text for t in tokens]
    line = " ".join(texts)
    avg_conf = sum(t.conf for t in tokens) / len(tokens) if tokens else 0.0

    date_val, date_note = _extract_date(line)
    # (x, 数値float, conf) — カンマ付きも必ず float 化
    nums: list[tuple[float, float, float]] = []
    for t in tokens:
        txt = t.text.strip()
        if not txt:
            continue
        if _token_looks_like_passbook_date(txt):
            continue
        if "/" in txt or "／" in txt:
            continue
        for m in AMOUNT_RE.finditer(txt):
            raw = m.group(0)
            amt = _parse_amount(raw)
            if amt is None:
                continue
            # 日付 YY/MM/DD が別トークン「25」「03」等に分かれたときの誤検出を抑止
            if "," not in raw and len(raw) <= 2 and amt <= 31:
                continue
            if amt < 1:
                continue
            nums.append((t.x, amt, t.conf))

    nums_sorted = sorted(nums, key=lambda x: x[0])
    # 同一行に万単位の金額があるのに 3 桁だけある → 日付や欄番号の破片のことが多い
    if nums_sorted and max(t[1] for t in nums_sorted) >= 10_000:
        nums_sorted = [t for t in nums_sorted if not (10 <= t[1] < 1000)]
    # 候補が多いほど厳しくノイズ除去（5個超: 1000円未満除去、3〜5個: 100円未満除去）
    if len(nums_sorted) > 5:
        filtered = [t for t in nums_sorted if t[1] >= 1000]
        nums_sorted = filtered if len(filtered) >= 2 else nums_sorted
    elif len(nums_sorted) > 3:
        filtered = [t for t in nums_sorted if t[1] >= 100]
        nums_sorted = filtered if len(filtered) >= 2 else nums_sorted
    amount_floats = [v for _, v, __ in nums_sorted]

    # 通帳は右側に お支払・お預かり・残高。左のノイズを避け **右から3つ**
    def _right_amounts(vals: list[float], k: int) -> list[float]:
        if len(vals) <= k:
            return vals
        return vals[-k:]

    status = "不明"
    note_parts: list[str] = []

    if avg_conf < 0.25:
        note_parts.append(f"OCR平均信頼度が低い({avg_conf:.2f})")

    if date_val is None:
        if date_note == "loose_date":
            note_parts.append("日付が厳密パターンに合わない（要確認）")
            status = "要確認"
        else:
            note_parts.append("日付が読み取れない")
            status = "不明"

    # 通帳: 左→右 が お支払金額(出金)・お預かり金額(入金)・残高
    入金 = 出金 = 計 = None
    n_amt = len(amount_floats)
    if n_amt >= 3:
        r3 = _right_amounts(amount_floats, 3)
        出金, 入金, 計 = r3[0], r3[1], r3[2]
        if n_amt > 3:
            note_parts.append(f"金額候補が{n_amt}個のため右端3列を採用")
        if date_val:
            # スキャンは誤読があり得るため、高信頼時のみ「確定」
            if avg_conf >= 0.55:
                status = "確定"
            else:
                status = "要確認"
                note_parts.append("OCR信頼度のため要確認（手元通帳と照合推奨）")
    elif n_amt == 2:
        a, b = amount_floats[0], amount_floats[1]
        # OCR で「支払・預かり・残高」のうち中列が空のとき 2 列になる。右列が残高とみなせるほど大きい比率なら 支払+残高 / 入金+残高 に分ける
        if b > a * 30 and b >= 10_000:
            # 「振込」「振替」は出金側にも付くため入金判定に含めない
            dep_hint = any(
                k in line
                for k in (
                    "入金",
                    "預り",
                    "預かり",
                    "給与",
                    "年金",
                    "配当",
                )
            )
            if dep_hint:
                出金, 入金, 計 = 0.0, a, b
                note_parts.append("金額2列を預かり・残高と解釈")
            else:
                出金, 入金, 計 = a, 0.0, b
                note_parts.append("金額2列を支払・残高と解釈")
            if date_val:
                status = "要確認" if avg_conf < 0.55 else "確定"
                if avg_conf < 0.55:
                    note_parts.append("OCR信頼度のため要確認（手元通帳と照合推奨）")
        else:
            r2 = _right_amounts(amount_floats, 2)
            出金, 入金 = r2[0], r2[1]
            計 = None
            note_parts.append("金額が2列のみ（残高列なしの可能性）")
            status = "要確認"
    elif n_amt == 1:
        出金 = amount_floats[-1]
        note_parts.append("金額が1つのみ（お支払のみ／他列欠落の可能性）")
        status = "要確認"
    else:
        note_parts.append("金額が検出できない")
        if status not in ("不明",):
            status = "要確認"

    # テキスト: 日付・純数字トークンを除き、採用した金額列より左を お支払先/摘要 に
    amount_region_left: float | None = None
    if nums_sorted and n_amt >= 1:
        k = min(n_amt, 3)
        amount_region_left = min(t[0] for t in nums_sorted[-k:])
    text_candidates: list[OcrToken] = []
    for t in sorted(tokens, key=lambda x: x.x):
        if _token_is_pure_amount(t.text):
            continue
        if _token_has_date(t.text) and len(t.text) <= 14:
            continue
        if amount_region_left is not None and t.x >= amount_region_left - 2:
            continue
        if not t.text.strip():
            continue
        text_candidates.append(t)

    支払先 = ""
    摘要 = ""
    if len(text_candidates) >= 2:
        支払先 = text_candidates[0].text.strip()[:80]
        摘要 = re.sub(
            r"\s+",
            " ",
            " ".join(x.text.strip() for x in text_candidates[1:]),
        ).strip()[:200]
    elif len(text_candidates) == 1:
        摘要 = text_candidates[0].text.strip()[:200]
    else:
        摘要 = re.sub(r"\s+", " ", line).strip()[:200]

    if status == "確定" and date_val and avg_conf < 0.5:
        status = "要確認"
        note_parts.append("行全体のOCR信頼度のため要確認")

    return {
        "日付": date_val or "",
        "科目": "",
        "支払先": 支払先,
        "お支払先": 支払先,
        "摘要": 摘要 or line[:200],
        "お支払金額": float(出金) if 出金 is not None else 0.0,
        "お預かり金額": float(入金) if 入金 is not None else 0.0,
        "入金": float(入金) if 入金 is not None else 0.0,
        "出金": float(出金) if 出金 is not None else 0.0,
        "計": float(計) if 計 is not None else 0.0,
        "取込ステータス": status,
        "OCR平均信頼度": round(avg_conf, 3),
        "備考": " / ".join(note_parts) if note_parts else "",
    }


def extract_yokohama_scan_pdf(
    raw: bytes,
    *,
    ocr_engine: str = "auto",
    filename: str = "",
) -> tuple[pd.DataFrame, list[str]]:
    """
    スキャンPDFを解析し、行ごとに DataFrame を返す。
    messages に全体向け警告（エンジン未導入など）。
    """
    messages: list[str] = []
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        embedded = _try_embedded_text(doc)
        use_embedded = len(embedded.strip()) > 80
        if use_embedded:
            messages.append("PDF内のテキストレイヤを使用しました（スキャンではなくコピー可能なPDFの可能性）。")
            lines = [ln.strip() for ln in embedded.splitlines() if ln.strip()]
            rows_out: list[dict] = []
            for ln in lines:
                fake_tokens = [OcrToken(0, 0, ln, 1.0)]
                rec = _classify_row(fake_tokens)
                rec["摘要"] = ln[:200]
                rec["取込ステータス"] = "要確認"
                rec["備考"] = (rec.get("備考") or "") + " / テキストレイヤのみの簡易取込"
                rows_out.append(rec)
            return pd.DataFrame(rows_out), messages

        all_tokens: list[OcrToken] = []
        easyocr_used_any = False
        easyocr_err: str | None = None
        tess_fallback_msg: str | None = None
        for page in doc:
            img = _enhance_scan_image(_page_to_rgb(page, dpi=400))
            tokens: list[OcrToken] | None = None
            if ocr_engine == "easyocr":
                try:
                    tokens = _normalize_tokens(_ocr_easyocr(img))
                    if tokens:
                        easyocr_used_any = True
                except Exception as e:
                    easyocr_err = str(e)
                    tokens = None
            elif ocr_engine == "tesseract":
                ts = _ocr_tesseract_best(img)
                tokens = _normalize_tokens(ts) if ts else None
            else:
                # auto: 日本語通帳スキャンは EasyOCR の方が読みやすい事例が多い → 先に試す
                try:
                    tokens = _normalize_tokens(_ocr_easyocr(img))
                    if tokens:
                        easyocr_used_any = True
                except Exception as e:
                    easyocr_err = str(e)
                    tokens = None
                if not tokens:
                    ts = _ocr_tesseract_best(img)
                    tokens = _normalize_tokens(ts) if ts else None
                    if tokens:
                        tess_fallback_msg = (
                            "EasyOCR が未導入・失敗・0件のため Tesseract に切り替えました。"
                        )
            if tokens:
                all_tokens.extend(tokens)

        if not all_tokens:
            if easyocr_err:
                messages.append(f"EasyOCR 失敗: {easyocr_err}")
            messages.append(
                "OCRで文字が得られませんでした。Tesseract（PATH 設定）または `pip install easyocr` を確認してください。"
            )
            return pd.DataFrame(), messages

        if tess_fallback_msg:
            messages.append(tess_fallback_msg)
        if ocr_engine == "easyocr" or easyocr_used_any:
            messages.append(
                "OCRエンジン: EasyOCR（自動モードでは優先。初回はモデルDLに時間がかかります）。"
            )
        elif ocr_engine in ("auto", "tesseract"):
            messages.append("OCRエンジン: Tesseract（複数前処理・PSMから自動選択）を使用しました。")
        messages.append(
            "【重要】スキャンPDFは列・活字の影響で誤認識が出やすいです。"
            "可能なら横浜信金の「入出金明細CSV」で取り込むのが確実です。"
            "スキャン結果は必ず手元の通帳と照合し、必要ならCSVで手修正してください。"
        )

        rows = _cluster_rows(all_tokens, y_tol=32.0)
        records: list[dict] = []
        for row_toks in rows:
            if len(row_toks) < 2:
                continue
            line_s = " ".join(t.text for t in row_toks)
            ls = line_s.replace(" ", "").replace("　", "")
            if "年月日" in ls and ("お支払" in ls or "お預かり" in ls or "お取引" in ls):
                continue
            if ls.strip() in ("1", "ページ",):
                continue
            if any(
                k in ls
                for k in (
                    "繰越しました",
                    "新通帳へ",
                    "差引残高を新",
                    "終差引残高",
                )
            ):
                continue
            records.append(_classify_row(row_toks))

        return pd.DataFrame(records), messages
    finally:
        doc.close()


def scan_df_to_bank_work(
    scan_df: pd.DataFrame,
    *,
    include_statuses: frozenset[str] = frozenset({"確定"}),
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    スキャン結果を既存の横浜CSV用パイプライン向け DataFrame に変換。
    戻り値: (work用, 除外された行, メッセージ)
    """
    msgs: list[str] = []
    if scan_df.empty:
        return pd.DataFrame(), scan_df, ["取込行がありません。"]

    sub = scan_df[scan_df["取込ステータス"].isin(include_statuses)].copy()
    excluded = scan_df[~scan_df["取込ステータス"].isin(include_statuses)].copy()

    if sub.empty:
        msgs.append("「確定」行がありません。要確認・不明のみの場合は、手動でCSV修正するか、取込オプションを変更してください。")

    # 横浜CSVプリセットと同じ列へ
    work = sub.copy()
    work["入金額"] = work["入金"].fillna(0)
    work["出金額"] = work["出金"].fillna(0)
    work = work.drop(columns=["入金", "出金", "計"], errors="ignore")

    # 科目・支払先が空なら摘要に統合済み
    # 複製ロジック（app の _combine_yokohama_summary と同じ）
    def _comb(df: pd.DataFrame) -> pd.Series:
        cols = [c for c in ("科目", "支払先", "摘要") if c in df.columns]
        if not cols:
            return df.get("摘要", pd.Series([""] * len(df)))
        acc = df[cols[0]].fillna("").astype(str).str.strip()
        for c in cols[1:]:
            acc = acc + " " + df[c].fillna("").astype(str).str.strip()
        return acc.str.replace(r"\s+", " ", regex=True).str.strip()

    work["摘要"] = _comb(work)
    return work, excluded, msgs
