# 本部経費ハブ（expense_hub）

親文書＝`Downloads/本部経費自動化_全体要件定義設計書_v1.md`。アプリのフォーマット選択「本部経費ハブ（アメックス×PLセルメモ照合）」から使う。

## 構成
| ファイル | 役割 |
|---|---|
| `sources/` | 入力ソース（1ソース＝1モジュール）。Phase 1＝`amex.py`。銀行・領収書・Amazon はここに足す |
| `pl_source.py` | PLの読み口（スプシ直結／xlsx）→ 共通の `Grid`（値＋メモ） |
| `pl_notes.py` | セルメモを1明細ずつ分解（日付・科目・相手先・内容・金額） |
| `matcher.py` | 原本×メモ照合（一致→名前違い→金額差異→計上月差→PL未反映） |
| `ledger.py` | 台帳：再取込拒否・監査ログ・PLバックアップ。secrets があれば台帳スプシ、無ければ SQLite（`get_ledger`） |
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

## 台帳の置き場
- secrets に `[gcp_service_account]` があり台帳スプシに届けば **台帳スプシ**（画面に「台帳：スプシ（再起動しても消えない）」）。ID は secrets の `ledger_spreadsheet_id`（無ければ既定の `1kTGjE4J…`）。サービスアカウントに **編集者** で共有しておく
- 届かなければ SQLite（「台帳：このPCのみ」＋理由を表示）
- 台帳スプシは1テーブル＝1タブ（import_batches / records / audit_log / pl_backups / pl_writes）。無ければタブと見出しを自動で作る

## 既知の制約（次段）
- 台帳スプシは **追記のみ**。records は更新のたびに1行増える＝同じ id は一番下の行が最新（集計時は id ごとに最終行を取る）
- PLバックアップの xlsx 本体はスプシに置けない（サービスアカウントに Drive 容量が無い）。台帳には日時・月・理由・バイト数・sha256 だけ残す。本体は画面の「バックアップをダウンロード」で保存する（Cloud のローカル保存は再起動で消える）
- 同時に2人が同じ原本を取り込むと、確認と追記の間に割り込まれて二重登録になりうる（1人運用の前提）
- PL未反映候補の反映先セル選択、按分ルール、利用先マスタ学習は未実装
