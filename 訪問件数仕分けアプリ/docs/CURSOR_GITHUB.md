# Cursor から GitHub に上げる（いちばん短い手順）

**このフォルダはすでに Git でコミット済み**です。やることは **2つだけ** です。

1. **GitHub のサイトで空のリポジトリを作る**  
2. **Cursor のターミナルで `git remote` と `git push` する**

スクリプト（`push-to-github.ps1`）は使わなくて大丈夫です。

---

## 手順 1 — GitHub でリポジトリを作る（ブラウザ）

1. ブラウザで **https://github.com** にログインする。  
2. 右上 **＋** → **New repository**。  
3. **Repository name** に名前を入れる（例: `homon-kensu-app`）。  
4. **Public** か **Private** を選ぶ。  
5. **Add a README** は **チェックしない**（空のまま）。  
6. **Create repository** を押す。

次の画面に **「…or push an existing repository from the command line」** と **3 行のコマンド**が出ます。  
**このうち `git remote add` と `git push` だけ使います**（`git branch -M main` は、すでに `main` なので不要なことが多いです）。

---

## 手順 2 — Cursor のターミナルで繋いで上げる

1. **Cursor** で `訪問件数仕分けアプリ` フォルダを開いたままにする。  
2. メニュー **ターミナル → 新しいターミナル**（または `` Ctrl+` ``）。  
3. 次を **1 行ずつ** 実行する（**`あなたのユーザー名` と `リポジトリ名` は自分のものに変える**）。

```powershell
cd "c:\Users\s2525\OneDrive\ドキュメント\デスクトップ\John_ai\訪問件数仕分けアプリ"
git remote add origin https://github.com/あなたのユーザー名/リポジトリ名.git
git push -u origin main
```

4. 初回だけ **GitHub のログイン**や **パスワードの代わりにトークン**を聞かれることがあります。表示に従って進める。

### 「remote origin already exists」と言われたら

以前 `origin` を追加済みのときです。次のあと、もう一度 `git push` してください。

```powershell
git remote remove origin
```

からやり直し、または **手順 2 の `git remote add` をもう一度**（上の `remove` のあとなら `add` からで OK）。

---

## うまくいったか確認

- ブラウザで GitHub のそのリポジトリを開き、`app.py` や `requirements.txt` が見えていれば成功です。

---

## つまずいたとき

| 症状 | 対処 |
|------|------|
| ログインできない | GitHub → Settings → Developer settings → **Personal Access Token** を作り、`git push` のパスワード欄に **トークンを貼る**（Classic で `repo` にチェック）。 |
| `failed to push` で拒否される | GitHub 上に **README だけあるリポジトリ**を作っていると競合することがあります。空のリポジトリで作り直すか、`git pull origin main --rebase` を試す（上級者向け）。 |
