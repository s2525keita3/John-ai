# 訪問件数仕分けアプリ

<div align="center">

**Ver.1.0** · 担当別訪問件数 PDF の集計 · 概算売上 · Streamlit

[要件定義](要件定義書.md) · [アーキテクチャ](docs/ARCHITECTURE.md) · [公開URL・共有](docs/DEPLOY.md) · [AGENTS](AGENTS.md) · `VERSION`

</div>

---

## 概要

- **担当別訪問件数レポート（PDF）** を読み、担当者ごとに **分数・時間・コード別内訳** を集計します。
- **介護保険相当の概算売上**（支援/介護の区分単価）に、**医療件数の暫定単価**を加算した **概算売上(円)** を算出します。
- **CSV / Excel / 汎用 PDF** からは行単位の明細を取り込み、カテゴリ別に集計できます。

再実装・保守のための **モジュール分担とデータ流れ** は [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) を参照してください。

---

## クイックスタート

```bash
cd 訪問件数仕分けアプリ
pip install -r requirements-local.txt
streamlit run app.py
```

ブラウザでアプリが開きます。左サイドバーから PDF をアップロードし、「担当別訪問件数 PDF として集計する」を ON にして取り込み実行してください。

### GitHub に載せる（Cursor から）

**いちばんわかりやすい手順:** **[docs/CURSOR_GITHUB.md](docs/CURSOR_GITHUB.md)**（空リポジトリを作る → `git remote add` → `git push` のみ）。  
その他: [docs/GITHUB_PUSH.md](docs/GITHUB_PUSH.md)（`gh` CLI・スクリプト版）。

### インストールなしで共有したい（URL を発行）

**[docs/DEPLOY.md](docs/DEPLOY.md)** を参照してください。  
代表的な方法は **GitHub に push → Streamlit Community Cloud でデプロイ** し、`https://xxxx.streamlit.app` のような **公開 URL** を発行することです。

---

## リポジトリ構成（Ver.1）

| パス | 役割 |
|------|------|
| `app.py` | Streamlit UI・フィルタ・ダッシュボード |
| `report_parser.py` | PDF 抽出・担当別集計 DataFrame |
| `service_fees.py` | 単価定数・概算売上（医療暫定を含む） |
| `medical_insurance_calc.py` / `medical_insurance_fees.py` | 医療保険の試算・参照定数（拡張用） |
| `要件定義書.md` | 要求・仕様の一次情報源 |
| `docs/ARCHITECTURE.md` | 依存関係・再構築チェックリスト |
| `VERSION` | リリースラベル |

---

## 開発メモ

- **単価の変更** → `service_fees.py` の定数のみ。
- **PDF レイアウトの変更** → `report_parser.py` の抽出ロジック。
- **画面の変更** → `app.py`（集計ロジックを UI に書かない）。

---

## ライセンス・免責

概算売上・暫定医療額は **業務上の目安** です。実請求・レセプトは別途ご確認ください。
