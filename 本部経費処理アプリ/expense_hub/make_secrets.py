"""
サービスアカウントの鍵JSON → Streamlit secrets（TOML）に変換する。鍵の中身は画面に出さない。
  py -3 本部経費処理アプリ\\expense_hub\\make_secrets.py "C:\\Users\\s2525\\Downloads\\<鍵>.json"
- リポジトリ直下 .streamlit\\secrets.toml に書く（git管理外）＝ローカル起動用
- 同じ内容をクリップボードにコピー＝Streamlit Cloud の Secrets 欄に貼る用
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def to_toml(info: dict) -> str:
    lines = ["[gcp_service_account]"]
    for k, v in info.items():
        lines.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("使い方: make_secrets.py <鍵JSONのパス>")
    info = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if info.get("type") != "service_account":
        sys.exit("サービスアカウントの鍵JSONではありません")
    toml = to_toml(info)

    out = REPO / ".streamlit" / "secrets.toml"
    out.parent.mkdir(exist_ok=True)
    body = out.read_text(encoding="utf-8") if out.exists() else ""
    if "[gcp_service_account]" in body:
        sys.exit(f"{out} には既に gcp_service_account があります（手で消してから再実行）")
    out.write_text(body + ("\n" if body and not body.endswith("\n") else "") + toml, encoding="utf-8")

    subprocess.run("clip", input=b"\xff\xfe" + toml.encode("utf-16-le"), shell=True, check=False)
    print(f"[OK] {out} に書きました（git管理外）")
    print("[OK] クリップボードにコピー済み → Streamlit Cloud の Secrets 欄に貼り付けてください")
    print(f"共有するメール: {info['client_email']}")


if __name__ == "__main__":
    main()
