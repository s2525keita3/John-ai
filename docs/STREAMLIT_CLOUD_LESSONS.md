# Streamlit Community Cloud デプロイでハマったこと（再発防止メモ）

このリポジトリで **「Error installing requirements」** が続いたあと、次の対応で **デプロイ成功** した。同じ構成で載せるときのチェックリストとして使う。

---

## 何がダメだったか（原因の整理）

### 1. サブフォルダの `requirements.txt` が優先された

Streamlit Community Cloud は、**エントリポイント（Main file）があるディレクトリを先に**見て `requirements.txt` を探し、そのあとリポジトリルートを見る。

- `本部経費処理アプリ/app.py` を指定していたとき、**`本部経費処理アプリ/requirements.txt`** がルートより先に使われた。
- ルートで直しても **デプロイ側はまだサブフォルダのファイル**を読んでいた可能性がある。

**回避:** 依存関係は **リポジトリルートの `requirements.txt` に一本化**する。サブフォルダには **`requirements-local.txt`** など別名でローカル開発用だけ置く（`requirements.txt` という名前をサブフォルダに置かない）。

参考: [App dependencies (Streamlit Docs)](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)

### 2. `requirements.txt` が「重すぎた」／競合しやすかった

- **`streamlit` を固定や二重指定**すると、Cloud 側のプリインストール版と **バージョン競合**しやすい。  
  公式でも **「streamlit はデフォルトで入っている。ピン留めしたいときだけ書く」** とある。
- **`pdfplumber` → cryptography など**、ビルドや解決が重い依存は、**不要なアプリでは入れない**（本部経費だけ載せるなら最小限に）。

**回避:** Cloud 用ルート `requirements.txt` は **Streamlit に含まれない追加パッケージだけ**（このリポでは例: `openpyxl`, `pymupdf`, `pytesseract`）。ローカル全部入れるのは `requirements-local.txt`。

### 3. Python 3.14 を選んでいた

プレビュー級のバージョンだと **manylinux ホイールが無い**パッケージがあり、`pip install` 自体が落ちやすい。

**回避:** **Python 3.12 または 3.11** に固定（App settings → General）。

### 4. Main file が日本語パスだけ（環境によっては不安定）

`本部経費処理アプリ/app.py` だけだと、パスや検索順の話と相まってトラブルしやすい。

**回避:** ルートに **ASCII 名のランチャー**（例: `honbu_keihi_app.py`）を置き、**Main file path にはそれを指定**する。中身は従来の `app.py` を読み込むだけ。

### 5. （補足）`packages.txt`

横浜信金スキャン PDF の **OCR** 用に、Linux では **`tesseract-ocr` / `tesseract-ocr-jpn`** が必要。リポジトリルートの `packages.txt` に列挙する（`pip` ではなく `apt`）。

---

## うまくいった構成（このリポジトリ）

| 項目 | 推奨 |
|------|------|
| Main file path | `honbu_keihi_app.py`（本部経費） / `homon_kensu_app.py`（訪問件数） |
| Requirements | 基本は **ルートの `requirements.txt`** のみ参照（サブフォルダに `requirements.txt` を置かない） |
| 訪問件数（homon_kensu） | ルート **`requirements.txt`** に streamlit / pandas / pdfplumber 等を **統合済み**（2026-04 以降）。**Advanced settings は空欄で可**。明示したい場合のみ `requirements_homon_kensu.txt` を指定。 |
| Python | **3.12 または 3.11** |
| ローカル開発 | 各アプリフォルダの **`requirements-local.txt`** で `pip install` |

---

## 次にデプロイするときの最短チェックリスト

1. [ ] ルートに **`requirements.txt`** があり、**Cloud 用に必要最小限**か  
2. [ ] サブフォルダに **`requirements.txt` という名前**が無い（ローカル用は `requirements-local.txt` 等）  
3. [ ] **Main file** は可能なら **ASCII のランチャー**  
4. [ ] App settings の **Python が 3.12 / 3.11**  
5. [ ] 変更後 **`git push`** してから **Reboot**  

---

## 関連ファイル

- ルート: `requirements.txt`, `honbu_keihi_app.py`, `homon_kensu_app.py`, `requirements_homon_kensu.txt`, `packages.txt`
- 本部経費: `本部経費処理アプリ/docs/DEPLOY.md`
- 訪問件数: `訪問件数仕分けアプリ/docs/DEPLOY.md`

---

*記録日: 2026-04-02（John-ai リポジトリでのデプロイ調査に基づく）*
