"""
振り分け結果の「メイン一覧・集計」から非表示にする摘要ルール。

支給控除で扱う給与振込・居宅への資金移動・マネフォ別取り込み等は、
CSV には残しつつ画面上の本部経費チェック対象から外す。
"""
from __future__ import annotations

from pathlib import Path

from classifier import _normalize_match_text

_ROOT = Path(__file__).resolve().parent
_OPTIONAL_HIDE_CSV = _ROOT / "halka_display_hide_keywords.csv"

# 追加の部分一致（1 行 1 キーワード・UTF-8）。ファイルが無くてもよい。
_extra_hide_keywords: tuple[str, ...] | None = None


def _load_optional_hide_keywords() -> tuple[str, ...]:
    global _extra_hide_keywords
    if _extra_hide_keywords is not None:
        return _extra_hide_keywords
    if not _OPTIONAL_HIDE_CSV.is_file():
        _extra_hide_keywords = ()
        return _extra_hide_keywords
    try:
        import pandas as pd

        df = pd.read_csv(_OPTIONAL_HIDE_CSV, encoding="utf-8-sig")
        col = "摘要キーワード" if "摘要キーワード" in df.columns else df.columns[0]
        kws = []
        for x in df[col].astype(str):
            t = x.strip()
            if not t or t.startswith("#") or t.lower() == "nan":
                continue
            kws.append(t)
        _extra_hide_keywords = tuple(kws)
    except Exception:
        _extra_hide_keywords = ()
    return _extra_hide_keywords


def should_hide_from_main_display(summary: str) -> bool:
    """
    True の行は「全明細」メイン表・勘定別集計・要確認表から除外する（CSV には残す）。
    """
    s = _normalize_match_text(summary)
    raw = summary or ""

    for kw in _load_optional_hide_keywords():
        if _normalize_match_text(kw) in s:
            return True

    # マネフォカード一括引落（明細は別 CSV）
    if ("df." in raw.lower() or "DF." in raw) and (
        "マネフォ" in s or "ﾏﾈﾌ" in raw
    ):
        return True

    # 居宅への資金移動
    if "ペイペイ" in s and "ハルカ" in s:
        return True

    if "ユ）タケシン" in s or "ユ)タケシン" in s:
        return True

    if not s.startswith("振込"):
        return False

    # 三菱 UFJ：「カ)」付き法人向け以外は給与振込扱いで非表示（NFKC で ）が ) になる）
    if "ミツビシユ" in s:
        if "カ）" in s or "カ)" in s:
            return False
        return True

    # みずほ：日本訪問看護財団（ザイ）等は表示、個人名振込は非表示
    if "ミズホ" in s:
        if "ザイ）" in s or "ザイ)" in s:
            return False
        return True

    # 三井住友：スターツアメニティ系（家賃）は表示、それ以外の個人振込は非表示
    if "ミツイスミトモ" in s:
        if any(x in s for x in ("スタ", "ツアメニ", "アメニティ")):
            return False
        return True

    if "ラクテン" in s:
        # マスタで「ラクテン ナカムラ＝支払報酬」等にしている法人向けは表示
        if "ナカムラ" in s:
            return False
        return True
    if "サイタマリソナ" in s:
        return True
    if "ヨコハマ" in s and "シンキン" not in s:
        return True
    if "リソナ" in s:
        return True

    return False
