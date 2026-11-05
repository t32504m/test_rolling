"""世帯条件とテンプレートから、カレンダー用の plan（plans/<名前>.js）を作る（Issue #22）。

出力は `window.ROLLING_PLAN = {...};` の JS ファイル。実験の当日に、ネットワークもサーバーもなしで、
calender.html?plan=<名前> を開くだけで印刷できるようにするため（file:// では fetch が使えない）。

例：
    python3 scripts/build_plan.py --adults 2 --days 3 --template standard --name a2-3d-standard
    # 参加者の世帯は private/ に出す（コミットしない）
    python3 scripts/build_plan.py --adults 1 --days 3 --template standard --name p01 --out-dir private/plans
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rotation import build_plan  # noqa: E402

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")  # calender.html が受け付ける名前と同じ


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--adults", type=int, required=True)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--infants", type=int, default=0)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--template", default=None, help="templates/index.json の id。省略するとマスタ全体")
    parser.add_argument("--exclude-tags", nargs="*", default=[])
    parser.add_argument("--exclude-ids", nargs="*", default=[])
    parser.add_argument("--name", required=True, help="出力ファイルの名前（英数字・-・_）")
    parser.add_argument("--out-dir", default="plans", help="出力先（リポジトリのルートからの相対パス）")
    args = parser.parse_args(argv)

    if not NAME_PATTERN.match(args.name):
        parser.error("--name は英数字・-・_ だけにしてください")

    household = {
        "adults": args.adults,
        "children": args.children,
        "infants": args.infants,
        "days": args.days,
    }
    plan = build_plan(household, args.template, exclude_tags=args.exclude_tags, exclude_ids=args.exclude_ids)

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.name}.js"
    body = json.dumps(plan, ensure_ascii=False, indent=1)
    path.write_text(f"window.ROLLING_PLAN = {body};\n", encoding="utf-8")
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
