# 本部経費ハブ（expense_hub）

親文書＝`Downloads/本部経費自動化_全体要件定義設計書_v1.md`。アプリのフォーマット選択「本部経費ハブ（アメックス×PLセルメモ照合）」から使う。

## 構成
| ファイル | 役割 |
|---|---|
| `sources/` | 入力ソース（1ソース＝1モジュール）。Phase 1＝`amex.py`。銀行・領収書・Amazon はここに足す |
| `pl_source.py` | PLの読み口（スプシ直結／xlsx）→ 共通の `Grid`（値＋メモ） |
| `pl_notes.py` | セルメモを1明細ずつ分解（日付・科目・相手先・内容・金額） |
| `matcher.py` | 原本×メモ照合（一致→名前違い→金額差異→計上月差→PL未反映） |
| `ledger.py` | 台帳（SQLite）：再取込拒否・監査ログ・PLバックアップ |
| `pipeline.py` | 一連の処理とCSV出力 |
| `ui.py` | 画面（ダッシュボード・明細・確認・反映候補） |

PLには書き込まない（Phase 1）。差異は人が承認するまで確定しない。

## スプシ直結の設定（渋谷さんの作業・1回だけ）
1. Google Cloud でプロジェクトを作り「Google Sheets API」を有効にする
2. サービスアカウントを作り、鍵（JSON）を発行する
3. 「2026年 ステーション収支計画」をサービスアカウントのメール（`…@….iam.gserviceaccount.com`）に **閲覧者** で共有
4. JSONの中身を Streamlit の secrets に入れる（Cloud＝アプリの Settings → Secrets／ローカル＝`.streamlit/secrets.toml`※git管理外）
   ```toml
   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "...@....iam.gserviceaccount.com"
   client_id = "..."
   token_uri = "https://oauth2.googleapis.com/token"
   ```
未設定のあいだは、スプシを xlsx でダウンロードして画面に置けば同じ照合ができる。

## 受入テスト
```
set EXPENSE_AMEX_CSV=...\activity (20).csv
set EXPENSE_PL_XLSX=...\収支計画.xlsx
py -3 -m pytest 本部経費処理アプリ/expense_hub/tests -q
```
実データはリポジトリに入れない。台帳の置き場＝`%USERPROFILE%\.john_expense_hub\`（`EXPENSE_HUB_DIR`で変更可）。

## 既知の制約（次段）
- Streamlit Cloud では再起動で台帳が消える → 台帳をスプシ（または Drive）に置く
- PL未反映候補の反映先セル選択、按分ルール、利用先マスタ学習は未実装
