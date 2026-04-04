# 本部経費処理アプリ（MVP）

月次の本部経費を **自社PL勘定項目** に振り分け、支給控除からの人件費集計、エネフリ／横浜信金など複数ソースに対応する Streamlit アプリです。

## ドキュメント（蓄積）

| 文書 | 内容 |
|------|------|
| [要件定義書.md](./要件定義書.md) | 目的・機能要件・対象外・用語（原本: 要件定義書 v2.docx に対応） |
| [仕様書.md](./仕様書.md) | モジュール構成・アルゴリズム・フォーマット別仕様・依存関係 |
| [docs/DEPLOY.md](./docs/DEPLOY.md) | **GitHub → Streamlit Community Cloud** で公開 URL を発行する手順（訪問件数アプリと同様） |

**原本の Word:** `本部経費処理 自動化 要件定義書 v2.docx`（ユーザーのドキュメントフォルダ）。追記・差分は上記 Markdown で管理する。

## いまできること（要約）

- **取引取込:** あおぞらCSV、アメックス activity CSV、横浜信金（CSV／スキャンPDF+OCR）、エネクスフリート請求PDF（本部カード0001〜0004の **（車番　計）** 金額のみ）、手動列名
- **振分:** 摘要キーワード（長いもの優先）＋金額レンジ＋任意データソース。オリコ摘要の除外オプション
- **結果:** 確定／要確認／判断不能、PL別集計、CSV DL
- **支給控除:** 本部対象者の **人件費(支給額,健康,介護,厚生,子ども)** 集計（タブ④）
- **初期マスタ:** 手打ちPL運用を反映した `sample_master.csv`

## まだやっていないこと（要件のうち）

- Googleスプレッドシート連携、MF仕訳からのマスタ自動生成、学習ループ、精度レポートの自動化 など（詳細は要件定義書）

## 起動

```bash
cd 本部経費処理アプリ
pip install -r requirements-local.txt
streamlit run app.py
# 同一仕様の別エントリ（halka_AI 用）:
# streamlit run halka_AI.py
```

**横浜信金スキャンPDF（OCR）:** `pip install -r requirements-local.txt` で **pytesseract** が入ります。**Tesseract 本体**は別途 PATH に必要です（未導入だと EasyOCR にフォールバック）。

- **Windows（推奨）:** `winget install UB-Mannheim.TesseractOCR`  
  インストール時に **Additional language data** で日本語（Japanese）を含めるか、後から `tessdata/jpn.traineddata` を配置してください。
- **日本語データ（jpn）:** 本体に `jpn` が無い場合は、[tessdata の jpn.traineddata](https://github.com/tesseract-ocr/tessdata/raw/main/jpn.traineddata) をこのアプリの **`tessdata/`** フォルダに保存すると、自動で使われます（`tessdata/README.txt` 参照）。
- **手動:** [UB Mannheim ビルド](https://github.com/UB-Mannheim/tesseract/wiki) からインストーラー実行し、**Additional language data** で日本語を含める。

### インストールなしで共有（公開 URL）

**[docs/DEPLOY.md](./docs/DEPLOY.md)** を参照。`John_ai` リポジトリを GitHub に push し、Streamlit Cloud の **Main file path** に `本部経費処理アプリ/app.py` を指定します。リポジトリ直下の **`packages.txt`**（親フォルダ `John_ai` に同梱）でクラウド上に Tesseract を入れられます。

## サンプルファイル

- `sample_master.csv` — 振分マスタ初期値
- `sample_transactions.csv` — 取引テスト用

## 改訂履歴（README）

| 日付 | 内容 |
|------|------|
| 2026-04 | 要件定義書・仕様書を追加し README を索引化。エネフリPDFは **（車番　計）** のカード別合計のみ取込・集計と確定 |
| 2026-04 | [docs/DEPLOY.md](./docs/DEPLOY.md)・リポジトリ直下 `packages.txt`（Streamlit Cloud 用 Tesseract）を追加 |
