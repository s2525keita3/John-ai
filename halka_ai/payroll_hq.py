"""
ジョン様「支給控除一覧表（部門別）」形式の xlsx/csv から、
本部メンバー（氏名行の列見出しに、UIで選んだキーワードが含まれる列）の人件費相当額を集計する。

人件費(支給額,健康,介護,厚生,子ども)
  = 支給合計
  + 健康保険料(会社) + 介護保険料(会社) + 厚生年金保険料(会社) + 子ども・子育て拠出金(会社)
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

# 一覧表1列目の行ラベル（完全一致）
ROW_LABELS = (
    "支給合計",
    "健康保険料(会社)",
    "介護保険料(会社)",
    "厚生年金保険料(会社)",
    "子ども・子育て拠出金(会社)",
)

RESULT_LABEL = "人件費(支給額,健康,介護,厚生,子ども)"

# 既定のキーワード（API利用時。Streamlit は app.HQ_PERSONNEL_KEYWORDS を既定全選択で渡す）
DEFAULT_HQ_SURNAMES = ("本部", "桜木町", "新子安", "白根", "さいわい")

# 従業員名・列見出しが入る行（0始まり）— **キーワード照合** のときは従来どおり 0 行目を氏名行とみなす運用もある
DEFAULT_NAME_ROW = 0

# --- halka 限定: 「支給控除一覧表（部門別）」で 1 行目=従業員番号、2 行目=氏名、本部は 001・002 のみ ---
HALKA_PAYROLL_CODE_ROW = 0
HALKA_PAYROLL_NAME_ROW = 1
HALKA_HQ_EMPLOYEE_CODES: Tuple[str, ...] = ("001", "002")


def parse_matrix_cell(v: Any) -> float:
    if pd.isna(v):
        return 0.0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "—", "NaT"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _norm_label(s: str) -> str:
    s = str(s).strip()
    s = re.sub(r"\s+", "", s)
    return s


def _find_row_index(df: pd.DataFrame, label: str) -> Optional[int]:
    """1列目が label と一致する行（先頭のみ）。"""
    target = _norm_label(label)
    for i in range(len(df)):
        cell = df.iat[i, 0]
        if pd.isna(cell):
            continue
        if _norm_label(cell) == target:
            return i
    return None


def _read_csv_path(p: Path) -> pd.DataFrame:
    last: Optional[Exception] = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(p, encoding=enc, header=None)
        except UnicodeDecodeError as e:
            last = e
    raise last or UnicodeDecodeError("read", b"", 0, 0, "unknown encoding")


def _read_csv_bytes(raw: bytes) -> pd.DataFrame:
    last: Optional[Exception] = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, header=None)
        except UnicodeDecodeError as e:
            last = e
    raise last or UnicodeDecodeError("read", b"", 0, 0, "unknown encoding")


def load_payroll_matrix(
    path_or_bytes: Union[bytes, str, Path], *, sheet_name: Union[int, str] = 0
) -> pd.DataFrame:
    """ヘッダー無しで全セルを DataFrame に読み込む。"""
    if isinstance(path_or_bytes, (str, Path)):
        p = Path(path_or_bytes)
        suf = p.suffix.lower()
        if suf in (".xlsx", ".xlsm"):
            return pd.read_excel(p, header=None, engine="openpyxl", sheet_name=sheet_name)
        return _read_csv_path(p)

    raw = path_or_bytes
    if not isinstance(raw, bytes):
        raise TypeError("bytes またはファイルパスを渡してください")

    # Streamlit upload: 拡張子不明時は xlsx マジックで分岐
    if len(raw) >= 2 and raw[:2] == b"PK":
        return pd.read_excel(io.BytesIO(raw), header=None, engine="openpyxl", sheet_name=sheet_name)
    return _read_csv_bytes(raw)


def _match_hq_columns(
    df: pd.DataFrame,
    name_row: int,
    surnames: Tuple[str, ...],
) -> List[Tuple[int, str]]:
    """(列インデックス, 表示名) のリスト。姓が surnames のいずれかに部分一致する列。"""
    if name_row >= len(df):
        return []
    out: List[Tuple[int, str]] = []
    for j in range(1, df.shape[1]):
        raw = df.iat[name_row, j]
        if pd.isna(raw):
            continue
        name = str(raw).strip()
        if name in ("-", "—", ""):
            continue
        if any(su in name for su in surnames):
            out.append((j, name))
    return out


def is_halka_dept_payroll_format(df: pd.DataFrame) -> bool:
    """1 列目が従業員番号／従業員の 2 行ヘッダなら True（部門別一覧の想定フォーマット）。"""
    if df.shape[0] < 2 or df.shape[1] < 2:
        return False
    a = str(df.iat[0, 0]).strip()
    b = str(df.iat[1, 0]).strip()
    return ("従業員番号" in a or a == "従業員番号") and ("従業員" in b or b == "従業員")


def _norm_employee_code(v: Any) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    if s.isdigit():
        return s.zfill(3)
    return s


def match_halka_hq_columns(
    df: pd.DataFrame,
    *,
    code_row: int = HALKA_PAYROLL_CODE_ROW,
    name_row: int = HALKA_PAYROLL_NAME_ROW,
) -> List[Tuple[int, str]]:
    """
    従業員番号が 001 / 002 の列のみ (列インデックス, 表示ラベル)。
    表示ラベル例: 「001 加藤 彼方」
    """
    want = frozenset(HALKA_HQ_EMPLOYEE_CODES)
    out: List[Tuple[int, str]] = []
    if code_row >= len(df) or name_row >= len(df):
        return []
    for j in range(1, df.shape[1]):
        code = _norm_employee_code(df.iat[code_row, j])
        if code not in want:
            continue
        nm = df.iat[name_row, j]
        nm_s = str(nm).strip() if not pd.isna(nm) else ""
        if nm_s in ("-", "—", ""):
            label = code
        else:
            label = f"{code} {nm_s}"
        out.append((j, label))
    out.sort(key=lambda x: x[0])
    return out


def find_halka_dept_reference_columns(
    df: pd.DataFrame,
    header_row: int = HALKA_PAYROLL_CODE_ROW,
) -> Dict[str, Tuple[int, str]]:
    """
    【訪問看護】【居宅】【全社計】列（ヘッダ行の文字列で判定）。
    戻り値: 論理キー → (列インデックス, ヘッダ表示文字列)
    """
    found: Dict[str, Tuple[int, str]] = {}
    for j in range(1, df.shape[1]):
        cell = df.iat[header_row, j]
        if pd.isna(cell):
            continue
        s = str(cell).strip()
        if "訪問看護" in s and "訪問看護" not in found:
            found["訪問看護"] = (j, s)
        elif "居宅" in s and "訪問看護" not in s and "居宅" not in found:
            found["居宅"] = (j, s)
        elif "全社計" in s and "全社計" not in found:
            found["全社計"] = (j, s)
    return found


def aggregate_halka_payroll_comparison(
    df: pd.DataFrame,
    *,
    code_row: int = HALKA_PAYROLL_CODE_ROW,
    name_row: int = HALKA_PAYROLL_NAME_ROW,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    本部（001・002）と【訪問看護】【居宅】【全社計】を横並びで比較する表。
    行は ROW_LABELS に加え最終行に RESULT_LABEL（各列で縦合計）。
    """
    errors: List[str] = []
    row_idx: Dict[str, int] = {}
    for lab in ROW_LABELS:
        ri = _find_row_index(df, lab)
        if ri is None:
            errors.append(f"行ラベル「{lab}」が見つかりません（1列目の表記を確認してください）")
        else:
            row_idx[lab] = ri

    hq_cols = match_halka_hq_columns(df, code_row=code_row, name_row=name_row)
    if not hq_cols:
        errors.append(
            f"本部列（従業員番号 {', '.join(HALKA_HQ_EMPLOYEE_CODES)}）が見つかりません。"
        )

    ref = find_halka_dept_reference_columns(df, header_row=code_row)
    for key, label in (("訪問看護", "【訪問看護】"), ("居宅", "【居宅】"), ("全社計", "【全社計】")):
        if key not in ref:
            errors.append(f"参照列「{label}」に一致するヘッダが見つかりません（1行目を確認してください）。")

    if not hq_cols or any(k not in ref for k in ("訪問看護", "居宅", "全社計")):
        return pd.DataFrame(), errors

    col_order: List[str] = []
    series: Dict[str, List[float]] = {}

    for j, lab_hq in hq_cols:
        col_order.append(f"本部 {lab_hq}")
        vals: List[float] = []
        for row_lab in ROW_LABELS:
            vals.append(
                parse_matrix_cell(df.iat[row_idx[row_lab], j]) if row_lab in row_idx else 0.0
            )
        vals.append(sum(vals))
        series[col_order[-1]] = vals

    sum_vals: List[float] = []
    for row_lab in ROW_LABELS:
        s = 0.0
        for j, _ in hq_cols:
            if row_lab in row_idx:
                s += parse_matrix_cell(df.iat[row_idx[row_lab], j])
        sum_vals.append(s)
    sum_vals.append(sum(sum_vals))
    col_order.append("本部計(001+002)")
    series["本部計(001+002)"] = sum_vals

    for key in ("訪問看護", "居宅", "全社計"):
        j, hdr = ref[key]
        title = hdr if hdr.startswith("【") else f"【{key}】"
        col_order.append(title)
        vals = []
        for row_lab in ROW_LABELS:
            vals.append(
                parse_matrix_cell(df.iat[row_idx[row_lab], j]) if row_lab in row_idx else 0.0
            )
        vals.append(sum(vals))
        series[col_order[-1]] = vals

    row_labels_display = list(ROW_LABELS) + [RESULT_LABEL]
    rows_out: List[Dict[str, Union[float, str]]] = []
    for i, rname in enumerate(row_labels_display):
        rec: Dict[str, Union[float, str]] = {"項目": rname}
        for c in col_order:
            rec[c] = series[c][i]
        rows_out.append(rec)

    return pd.DataFrame(rows_out), errors


def aggregate_halka_hq_personnel_cost_only(
    df: pd.DataFrame,
    *,
    code_row: int = HALKA_PAYROLL_CODE_ROW,
    name_row: int = HALKA_PAYROLL_NAME_ROW,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    001・002 のみを対象に、aggregate_hq_personnel_cost と同じ縦型（氏名・各項目・人件費合計・本部合計行）。
    """
    errors: List[str] = []
    row_idx: Dict[str, int] = {}
    for lab in ROW_LABELS:
        ri = _find_row_index(df, lab)
        if ri is None:
            errors.append(f"行ラベル「{lab}」が見つかりません（1列目の表記を確認してください）")
        else:
            row_idx[lab] = ri

    cols = match_halka_hq_columns(df, code_row=code_row, name_row=name_row)
    if not cols:
        errors.append("本部（001・002）の列が見つかりません。")
        return pd.DataFrame(), errors

    rows_out: List[Dict[str, Union[float, str]]] = []
    for j, display_name in cols:
        rec: Dict[str, Union[float, str]] = {"氏名": display_name}
        total = 0.0
        for lab in ROW_LABELS:
            if lab not in row_idx:
                rec[lab] = 0.0
                continue
            v = parse_matrix_cell(df.iat[row_idx[lab], j])
            rec[lab] = v
            total += v
        rec[RESULT_LABEL] = total
        rows_out.append(rec)

    out_df = pd.DataFrame(rows_out)
    if not out_df.empty:
        sum_row: Dict[str, Union[float, str]] = {"氏名": "本部合計(001+002)"}
        for lab in ROW_LABELS:
            sum_row[lab] = float(out_df[lab].sum()) if lab in out_df.columns else 0.0
        sum_row[RESULT_LABEL] = float(out_df[RESULT_LABEL].sum())
        out_df = pd.concat([out_df, pd.DataFrame([sum_row])], ignore_index=True)

    return out_df, errors


def aggregate_hq_personnel_cost(
    df: pd.DataFrame,
    *,
    name_row: int = DEFAULT_NAME_ROW,
    surnames: Tuple[str, ...] = DEFAULT_HQ_SURNAMES,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    本部対象者ごとに ROW_LABELS の金額を読み取り、5項目の縦計＝ RESULT_LABEL を付与。
    戻り値: (結果 DataFrame, エラーメッセージ一覧)
    """
    errors: List[str] = []
    row_idx: Dict[str, int] = {}
    for lab in ROW_LABELS:
        ri = _find_row_index(df, lab)
        if ri is None:
            errors.append(f"行ラベル「{lab}」が見つかりません（1列目の表記を確認してください）")
        else:
            row_idx[lab] = ri

    cols = _match_hq_columns(df, name_row, surnames)
    if not cols:
        errors.append(
            f"{name_row + 1}行目の氏名から、本部対象（{', '.join(surnames)}）に一致する列がありません。"
        )

    if not cols:
        return pd.DataFrame(), errors

    rows_out: List[Dict[str, Union[float, str]]] = []
    for j, display_name in cols:
        rec: Dict[str, Union[float, str]] = {"氏名": display_name}
        total = 0.0
        for lab in ROW_LABELS:
            if lab not in row_idx:
                rec[lab] = 0.0
                continue
            v = parse_matrix_cell(df.iat[row_idx[lab], j])
            rec[lab] = v
            total += v
        rec[RESULT_LABEL] = total
        rows_out.append(rec)

    out_df = pd.DataFrame(rows_out)
    if not out_df.empty:
        sum_row: Dict[str, Union[float, str]] = {"氏名": "本部合計"}
        for lab in ROW_LABELS:
            sum_row[lab] = float(out_df[lab].sum()) if lab in out_df.columns else 0.0
        sum_row[RESULT_LABEL] = float(out_df[RESULT_LABEL].sum())
        out_df = pd.concat([out_df, pd.DataFrame([sum_row])], ignore_index=True)

    return out_df, errors
