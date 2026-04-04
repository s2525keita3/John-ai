# GitHub に push する手順（このフォルダは既に Git 初期化済み）

ローカルでは **`main` ブランチ**に初回コミットまで完了しています。

---

## いちばん簡単: スクリプトで作成＋push（推奨）

**GitHub CLI (`gh`)** が入っていると、**リポジトリ作成と `git push` をまとめて**実行できます。

1. **GitHub CLI** をまだ入れていない場合（管理者権限の PowerShell など）:
   ```powershell
   winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
   ```
2. プロジェクトの **`訪問件数仕分けアプリ` フォルダ**に移動してから実行します。

   **すでに PowerShell を開いている場合**（おすすめ）— 次の **2 行だけ**（`powershell` を二度と書かない）:

   ```powershell
   cd "c:\Users\s2525\OneDrive\ドキュメント\デスクトップ\John_ai\訪問件数仕分けアプリ"
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\scripts\push-to-github.ps1
   ```

   （`-ExecutionPolicy Bypass` と書く。`-Bypass` だけだとエラーになります。）

   **コマンドプロンプト (cmd) から** 別プロセスで PowerShell を起動するとき:

   ```cmd
   cd /d "c:\Users\s2525\OneDrive\ドキュメント\デスクトップ\John_ai\訪問件数仕分けアプリ"
   powershell -ExecutionPolicy Bypass -File .\scripts\push-to-github.ps1
   ```

   ※ フォルダパスの **直後に `powershell` と続けない**でください。`\訪問件数仕分けアプリ\powershell` のように見えるとエラーになります。
3. **初回だけ** `gh auth login` でブラウザが開き、GitHub にログインします（これはあなた本人の許可が必要で、自動では代行できません）。
4. 既定のリポジトリ名は **`homon-kensu-app`**（**非公開 private**）。変える場合は例:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\push-to-github.ps1 -RepoName "別の名前"
   ```

既に `origin` が設定されている場合は、手動で `git remote remove origin` してからやり直すか、手順「2」を使ってください。

---

## 手動: 空のリポジトリを Web で作ってから push

### 1. GitHub でリポジトリを作成

1. [github.com](https://github.com) にログイン  
2. **Repositories** → **New**  
3. Repository name: 例 `homon-kensu-app`（任意）  
4. **Public** または **Private** を選択  
5. **Add a README** は **チェックしない**（既にローカルにあるため）  
6. **Create repository**

### 2. リモートを追加して push

画面に表示される URL（HTTPS）をコピーし、**自分のユーザー名とリポジトリ名**に置き換えて PowerShell で実行します。

```powershell
cd "訪問件数仕分けアプリのパス"
git remote add origin https://github.com/あなたのユーザー名/リポジトリ名.git
git push -u origin main
```

初回はブラウザまたはトークンで GitHub 認証を求められます。

- **HTTPS:** Personal Access Token（Classic）がパスワード欄に必要な場合があります。  
- **SSH** を使う場合は、GitHub の SSH URL で `git remote add origin git@github.com:...` としてください。

### 3. 確認

GitHub のリポジトリページに `app.py` や `requirements.txt` が見えれば成功です。  
Streamlit Cloud ではこのリポジトリを選び、**Main file path** に `app.py` を指定してデプロイできます（`docs/DEPLOY.md`）。
