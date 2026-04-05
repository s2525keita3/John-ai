# halka_AI（独立パッケージ）

`本部経費処理アプリ`（JOHN）とは **コードを共有しません**。ここだけ修正すれば halka 向けの挙動を変えられます。

## 起動

リポジトリルート（`John_ai`）で:

```bash
pip install -r halka_ai/requirements-local.txt
streamlit run halka_ai/app.py
```

Streamlit Community Cloud では Main file path に **`halka_ai_app.py`**（親フォルダの ASCII エントリ）。

## 構成

| ファイル | 役割 |
|----------|------|
| `app.py` | Streamlit UI・マネフォ／あおぞら取込・振分・人件費タブ |
| `halka_master.csv` | 既定の振分マスタ |
| `classifier.py` | 摘要キーワード→PL 分類 |
| `pl_accounts.py` | 自社PLドロップダウン一覧 |
| `aozora_filters.py` | あおぞら向け除外ルール |
| `filters.py` | オリコ摘要除外など |
| `csv_loader.py` | CSV 文字コード自動判定 |
| `payroll_hq.py` | 支給控除一覧表の集計 |

## 決めているルール（要約）

- 横浜信用金庫・エネクスフリートの取込は **ない**
- アメックス向けの自動除外ルールは **ない**（旧仕様どおり）
- 摘要に **APｱﾌﾟﾗｽ / APアプラス** → 出金額 **50%按分**（リース・複合機按分）
- マネフォカードは **利用明細CSV**（`取引日時`・`支払先`・`金額` 等）

`pl_accounts` や `halka_master.csv` を編集すると、JOHN 側の `本部経費処理アプリ` には影響しません（別コピーです）。
