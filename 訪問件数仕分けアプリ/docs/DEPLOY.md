# 公開 URL を発行して共有する（訪問件数仕分けアプリ）

「自分の PC だけ」ではなく **ブラウザの URL を知っている人なら誰でも開ける** 状態にする手順です。

---

## おすすめ: Streamlit Community Cloud（無料枠あり）

Streamlit 公式のホスティング。**GitHub にコードを置き**、連携すると **`https://xxxx.streamlit.app`** 形式の URL が自動で付きます。

### 前提

- [GitHub](https://github.com) アカウント
- このアプリのフォルダを **Git リポジトリ** として GitHub に push 済み（中身は `訪問件数仕分けアプリ` 直下が `app.py` になるよう配置）

### 手順（概要）

1. **GitHub にリポジトリを作成**し、`app.py`・`requirements.txt`・同階層の `.py` をすべて push する。  
   - リポジトリの **ルート** に `app.py` がある構成が分かりやすいです（サブフォルダだけ push する場合は手順 3 で Main file path を指定）。

2. [Streamlit Community Cloud](https://share.streamlit.io/) にログイン（GitHub で連携）。

3. **「New app」** で次を設定します（このリポジトリ **John-ai** の場合）。

   | 項目 | 推奨値 |
   |------|--------|
   | Repository | 本リポジトリ |
   | Branch | `main` |
   | **Main file path** | **`homon_kensu_app.py`**（リポジトリルート。日本語フォルダ名を Main に直接書かない） |
   | **Advanced settings → Requirements file** | **空欄のまま**でよい（ルートの `requirements.txt` に pdfplumber 等を含めてある）。明示したい場合のみ **`requirements_homon_kensu.txt`** を指定。 |

4. **Deploy** を押す。ビルド完了後、**Manage app → Reboot** で再起動してもよい。

5. **動作確認**  
   - ブラウザでアプリを開き、**タブのタイトル**と**左サイドバー先頭**に **`アプリ版` / `v` と版番号**（`訪問件数仕分けアプリ/VERSION` の先頭行。例: **1.0.10**）が表示されること。  
   - 版が古いときはデプロイがまだ取り込んでいないので、数分待つか **Redeploy / Reboot**、GitHub の **最新 `main`** を確認する。

### 注意（運用）

| 項目 | 内容 |
|------|------|
| **データ** | アップロードした PDF は **サーバー上の一時領域** に載ります。機密データの取り扱いは組織のルールに従ってください。 |
| **無料枠** | スリープやリソース制限があります。業務で常時・大量利用する場合は有料プランや自社サーバを検討してください。 |
| **認証** | デフォルトでは **URL を知っている人は誰でもアクセス可能** です。職場だけに限定したい場合は [Streamlit の認証](https://docs.streamlit.io/knowledge-base/deploy/authentication-without-sso) や、GitHub のプライベートリポジトリ＋招待制 Cloud などを検討してください。 |

---

## 手早く試すだけ: ngrok（自分の PC で動かしたまま一時 URL）

社内だけ・短時間だけ共有する場合、**ローカルで `streamlit run app.py` を起動した状態**でトンネルを張る方法です。

1. [ngrok](https://ngrok.com/) に登録し、クライアントをインストール。
2. ターミナルで Streamlit を起動（例: `streamlit run app.py --server.port 8501`）。
3. 別ターミナルで `ngrok http 8501` を実行すると、**一時的な `https://....ngrok.io`** が表示されます。

PC を閉じると URL は無効になります。本番共有には向きません。

---

## その他の選択肢（概要）

| 方式 | 向く用途 |
|------|----------|
| **Azure Container Apps / Cloud Run / ECS** など | 社内規定でクラウドに載せる必要がある場合 |
| **社内サーバ + リバースプロキシ** | URL を社内 DNS で固定したい場合 |

いずれも「コンテナ化または `streamlit run` を常駐させる」イメージです。詳細は各クラウドのドキュメントを参照してください。

---

## まとめ

- **誰でも URL で使わせたい（まずは簡単に）** → **Streamlit Community Cloud + GitHub** が手軽です。  
- **今日だけ見せたい** → **ngrok**。  
- **機密・認証必須** → Cloud の認証機能や、社内インフラでのホスティングを検討してください。
