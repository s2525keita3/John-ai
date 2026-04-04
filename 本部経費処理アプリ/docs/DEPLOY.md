# 公開 URL を発行して共有する（本部経費処理アプリ / JOHN_AI）

「自分の PC だけ」ではなく **ブラウザの URL を知っている人なら誰でも開ける** 状態にする手順です。  
訪問件数仕分けアプリと同じく **Streamlit Community Cloud + GitHub** を前提にしています。

---

## おすすめ: Streamlit Community Cloud（無料枠あり）

[Streamlit Community Cloud](https://share.streamlit.io/) にログイン（GitHub 連携）し、リポジトリからデプロイします。

### 前提

- [GitHub](https://github.com) アカウント
- 次のいずれかを **Git リポジトリとして push 済み**
  - **A:** `John_ai` フォルダ丸ごと（デスクトップの `John_ai` リポジトリ）
  - **B:** `本部経費処理アプリ` の中身だけをリポジトリのルートに置いたもの

### 手順（概要）

1. GitHub にリポジトリを用意し、**リポジトリルートの `requirements.txt`**・**`honbu_keihi_app.py`**・`本部経費処理アプリ` 内の **`.py`** などをすべて push する（Streamlit Cloud は **サブフォルダの `requirements.txt` を優先**しがちなため、依存は **ルートに集約**し、起動は **`honbu_keihi_app.py`** を指定する）。

2. [share.streamlit.io](https://share.streamlit.io/) で **New app** を開く。

3. 次のように設定する。

   | 設定 | 値の例 |
   |------|--------|
   | Repository | 上記の GitHub リポジトリ |
   | Branch | `main`（または利用中のブランチ） |
   | Main file path | **A の場合（推奨）:** `honbu_keihi_app.py`（ASCII のみ・ルート）<br>**従来:** `本部経費処理アプリ/app.py` |

   **halka_AI エントリで公開したい場合**は Main file path を  
   `本部経費処理アプリ/halka_AI.py`（A の場合）にする。

4. **Deploy** を押す。ビルド完了後に **`https://xxxx.streamlit.app`** が発行されます。

### リポジトリ直下の `packages.txt`（OCR 用・任意）

リポジトリの **ルート**（`John_ai` を丸ごと push するなら `John_ai` 直下）に `packages.txt` を置くと、Streamlit Cloud の Linux 環境で **Tesseract（日本語）** を入れられます。横浜信金の **スキャン PDF OCR** をクラウドでも試すときに有効です。

```
tesseract-ocr
tesseract-ocr-jpn
```

`packages.txt` が無くても **CSV／Excel 取込**や **あおぞら・アメックス・エネフリ**は動きます。OCR は **EasyOCR**（`requirements.txt` に含める場合）に依存する方法もありますが、ビルドが重くなります。

### 注意（運用）

| 項目 | 内容 |
|------|------|
| **データ** | アップロードした CSV／PDF は **サーバー上の一時領域** に載ります。機密の取り扱いは社内ルールに従ってください。 |
| **無料枠** | スリープ・リソース制限があります。常時運用は有料プランや自社サーバも検討してください。 |
| **認証** | デフォルトでは **URL を知っている人は誰でもアクセス可能** です。限定したい場合は [Streamlit の認証](https://docs.streamlit.io/knowledge-base/deploy/authentication-without-sso) やプライベートリポジトリ＋招待制を検討してください。 |

---

## GitHub に上げる（Cursor から）

**John_ai 全体を push する例**（パスは環境に合わせて変える）:

```powershell
cd "c:\Users\s2525\OneDrive\ドキュメント\デスクトップ\John_ai"
git status
git add .
git commit -m "本部経費処理アプリ: デプロイ用"
git remote add origin https://github.com/あなたのユーザー名/リポジトリ名.git
git push -u origin main
```

初回のみ GitHub で空リポジトリを作成し、`git remote` / `git push` の詳細は訪問件数アプリの **[訪問件数仕分けアプリ/docs/CURSOR_GITHUB.md](../../訪問件数仕分けアプリ/docs/CURSOR_GITHUB.md)** と同じ考え方です。

---

## 手早く試すだけ: ngrok

社内だけ・短時間だけ共有する場合は、ローカルで `streamlit run app.py` を起動したうえで [ngrok](https://ngrok.com/) などでトンネルを張る方法もあります（訪問件数アプリの `docs/DEPLOY.md` と同様）。

---

## まとめ

- **URL で共有したい** → **GitHub に push → Streamlit Community Cloud** で `本部経費処理アプリ/app.py` を指定。  
- **OCR もクラウドで** → リポジトリルートに `packages.txt`（Tesseract）を検討。  
- **今日だけ見せる** → **ngrok**。
