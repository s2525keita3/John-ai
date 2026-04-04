# AI / 開発者向けメモ（Ver.1）

変更時は **次の順で読む** と手戻りが減ります。

1. **`要件定義書.md`** — 仕様の正解はここ。  
2. **`docs/ARCHITECTURE.md`** — どのファイルに何を書くか。  
3. **`app.py`** の `add_revenue_columns` / `drop_cols` / `_render_report_dashboard_section` 周辺。  
4. **`report_parser.summarize_report_pdf`** — PDF 抽出の唯一の正規化箇所。  
5. **`service_fees.py`** — 単価・概算売上（医療暫定の加算）。

**やらないこと:** UI に複雑な数式を増やす。単価・区分は `service_fees`、抽出は `report_parser` に集約する。

**バージョン:** リリース境界は `VERSION` と `要件定義書.md` の改訂履歴で揃える。

**Cursor:** `.cursor/rules/*.mdc` に、コード変更時に **ローカル確認 → git push → Streamlit Cloud** を提案するルールを入れてある。
