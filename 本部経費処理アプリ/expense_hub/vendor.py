"""
利用先名の正規化。カード明細は「店名＋全角スペース＋都道府県＋市区町村」の形で来るので、
所在地と記号を落として比較用のキーにする。
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_PREFS = (
    "北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|"
    "新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|"
    "奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|"
    "熊本県|大分県|宮崎県|鹿児島県|沖縄県"
)
# 都道府県名の途中で切れている明細（例「?神奈川県横浜」）もあるので、都道府県以降を落とす
_PREF_TAIL = re.compile(rf"[?？]?\s*({_PREFS}).*$")
_NOISE = re.compile(r"[\s　?？・･,，.．、。（）()「」\[\]〔〕*＊\-－ー]+")
_CORP = re.compile(r"(株式会社|有限会社|合同会社|\(株\)|（株）|\(有\)|（有）|INC|CO|LTD|CORP)")


def normalize_vendor(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw or "").strip()
    s = _PREF_TAIL.sub("", s)
    s = s.upper()
    s = _CORP.sub("", s)
    s = _NOISE.sub("", s)
    return s


def vendor_similarity(a: str, b: str) -> float:
    """正規化済みキー同士の近さ（0〜1）。片方がもう片方を含めば一致扱い。"""
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


# 同じ請求を部門ごとのメモで別の呼び方にしているもの（按分照合用）。キーは正規化済み利用先に含まれる語
ALIASES = {
    "ソフトバンク": ("ソフトバンク", "SOFTBANK", "スマホ", "携帯"),
}


def alias_words(vendor_normalized: str) -> tuple[str, ...]:
    for key, words in ALIASES.items():
        if key in vendor_normalized:
            return words
    return ()


def mentions(text: str, words: tuple[str, ...]) -> bool:
    t = normalize_vendor(text)
    return any(normalize_vendor(w) in t for w in words)
