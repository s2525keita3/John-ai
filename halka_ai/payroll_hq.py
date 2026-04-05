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

# 従業員名・列見出しが入る行（0始まり）＝表の **1行目** 固定
DEFAULT_NAME_ROW = 0


def parse_matrix_cell(v) -> float:
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


def load_payroll_matrix(path_or_bytes: bytes | str | Path, *, sheet_name: int | str = 0) -> pd.DataFrame:
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


def _read_csv_path(p: Path) -> pd.DataFrame:
    last: Exception | None = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(p, encoding=enc, header=None)
        except UnicodeDecodeError as e:
            last = e
    raise last or UnicodeDecodeError("read", b"", 0, 0, "unknown encoding")


def _read_csv_bytes(raw: bytes) -> pd.DataFrame:
    last: Exception | None = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, header=None)
        except UnicodeDecodeError as e:
            last = e
    raise last or UnicodeDecodeError("read", b"", 0, 0, "unknown encoding")


def _norm_label(s: str) -> str:
    s = str(s).strip()
    s = re.sub(r"\s+", "", s)
    return s


def _find_row_index(df: pd.DataFrame, label: str) -> int | None:
    """1列目が label と一致する行（先頭のみ）。"""
    target = _norm_label(label)
    for i in range(len(df)):
        cell = df.iat[i, 0]
        if pd.isna(cell):
            continue
        if _norm_label(cell) == target:
            return i
    return None


def _match_hq_columns(
    df: pd.DataFrame,
    name_row: int,
    surnames: tuple[str, ...],
) -> list[tuple[int, str]]:
    """(列インデックス, 表示名) のリスト。姓が surnames のいずれかに部分一致する列。"""
    if name_row >= len(df):
        return []
    out: list[tuple[int, str]] = []
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


def aggregate_hq_personnel_cost(
    df: pd.DataFrame,
    *,
    name_row: int = DEFAULT_NAME_ROW,
    surnames: tuple[str, ...] = DEFAULT_HQ_SURNAMES,
) -> tuple[pd.DataFrame, list[str]]:
    """
    本部対象者ごとに ROW_LABELS の金額を読み取り、5項目の縦計＝ RESULT_LABEL を付与。
    戻り値: (結果 DataFrame, エラーメッセージ一覧)
    """
    errors: list[str] = []
    row_idx: dict[str, int] = {}
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

    rows_out: list[dict] = []
    for j, display_name in cols:
        rec: dict[str, float | str] = {"氏名": display_name}
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
        sum_row: dict[str, float | str] = {"氏名": "本部合計"}
        for lab in ROW_LABELS:
            sum_row[lab] = float(out_df[lab].sum()) if lab in out_df.columns else 0.0
        sum_row[RESULT_LABEL] = float(out_df[RESULT_LABEL].sum())
        out_df = pd.concat([out_df, pd.DataFrame([sum_row])], ignore_index=True)

    return out_df, errors
