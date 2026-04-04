# John_ai — デザイン参照（全体方針）

このワークスペース（John_ai）で **画面・UI・見た目** を新規に作る・大きく変えるときは、**必ず先に** 次のリソースを参照してから実装する。

## 一次参照（デザインシステムの土台）

**[VoltAgent / awesome-design-md](https://github.com/VoltAgent/awesome-design-md)**

- 有名プロダクト由来の **DESIGN.md**（Google Stitch 形式）が集められたリポジトリ。
- 各サイトの `DESIGN.md` には、配色・タイポ・コンポーネント・レイアウト・Elevation・レスポンシブ・Agent 向けプロンプトなどが整理されている。
- **使い方（推奨）**
  1. 上記リポジトリの [`design-md`](https://github.com/VoltAgent/awesome-design-md/tree/main/design-md) から、作りたい雰囲気に近いサイトのフォルダを選ぶ。
  2. その中の **`DESIGN.md`** をプロジェクトまたはサブプロジェクト（例: `本部経費処理アプリ/`）にコピーし、名前は `DESIGN.md` のまま置くか、用途が分かる名前で併置する。
  3. 実装（Streamlit の `st.set_page_config` / `theme` / カスタム CSS、HTML テンプレートなど）は、**その DESIGN.md のトークンとルールに合わせる**。

## 実装時のルール

- **新規画面・ダッシュボード・フォーム** を追加するとき: 先に `DESIGN.md`（awesome-design-md 由来）を開き、**Color / Typography / Component / Spacing** を優先順に反映する。
- **既存アプリの小さな修正**（バグ・ロジックのみ）で UI を触らない場合は、この手順は省略してよい。
- Streamlit では `.streamlit/config.toml` や `st.markdown(unsafe_allow_html=True)` ＋ CSS で、DESIGN.md の色・フォントに近づける。

## このファイルの役割

- John_ai **全体**の「デザインの出発点」をここに固定する。
- Cursor のプロジェクトルール（`.cursor/rules/design-reference.mdc`）からも参照される。

## 関連リンク

- [Awesome DESIGN.md（README）](https://github.com/VoltAgent/awesome-design-md) — 収録サイト一覧と Stitch 形式の説明
