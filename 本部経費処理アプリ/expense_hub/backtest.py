"""
通年バックテスト：アメックスの通年CSVを利用月ごとに分け、各月で照合を回して指標を出す。
ルールを変えたとき「過去の月が悪くならないか」を見るためのもの（学習ログの指標欄の元）。

  py -3 -m expense_hub.backtest "C:\\...\\activity (28).csv" [--months 1-8] [--json out.json]
PL はスプシ直結（secrets）。書き込みはしない。
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import sys
import tomllib
from pathlib import Path

from .models import Status
from .pipeline import pl_sheets, run
from .pl_source import Grid, grids_from_sheets

SECRETS = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"


def split_by_usage_month(raw: bytes) -> dict[int, bytes]:
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    by: dict[int, list] = collections.defaultdict(list)
    for r in rows[1:]:
        if r and r[0].strip():
            by[int(r[0].split("/")[1])].append(r)
    out = {}
    for m, rs in by.items():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(rows[0])
        w.writerows(rs)
        out[m] = buf.getvalue().encode("cp932")
    return out


def run_backtest(raw: bytes, grids: dict[str, Grid], months: range) -> list[dict]:
    parts = split_by_usage_month(raw)
    results = []
    for m in months:
        if m not in parts:
            continue
        res = run(parts[m], f"amex_{m}.csv", grids, f"{m}月")
        s = res.summary
        review = [r for r in res.records if r.approval_status == Status.REVIEW_REQUIRED]
        results.append({
            "利用月": m,
            "行数": s["行数"],
            "自動確認": s["自動確認済み"],
            "要確認": s["要確認"],
            "PL未反映": s["PL未反映"],
            "計上月差": s["計上月差"],
            "差異額": s["差異額"],
            "要確認の内訳": [
                {"日付": str(r.transaction_date), "利用先": r.vendor_raw.strip()[:24], "金額": r.amount, "理由": r.judgement_reason[:80]}
                for r in review
            ],
        })
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--months", default="1-8")
    ap.add_argument("--json")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.months.split("-"))
    sa = tomllib.load(open(SECRETS, "rb"))["gcp_service_account"]
    grids = grids_from_sheets(sa, pl_sheets())
    results = run_backtest(Path(a.csv).read_bytes(), grids, range(lo, hi + 1))
    auto = sum(r["自動確認"] for r in results)
    rv = sum(r["要確認"] for r in results)
    for r in results:
        print(f"{r['利用月']}月 行{r['行数']} 自動{r['自動確認']} 要確認{r['要確認']} 未反映{r['PL未反映']} 月差{r['計上月差']} 差異額{r['差異額']:,}")
        for x in r["要確認の内訳"]:
            print("    ", x["日付"], x["利用先"], f"{x['金額']:,}", "|", x["理由"])
    print(f"合計 自動{auto} 要確認{rv} 自動確認率 {auto / (auto + rv):.0%}" if auto + rv else "データなし")
    if a.json:
        Path(a.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
