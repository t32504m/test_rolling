"""オーナー向けの常識チェック報告を作る。

コードを読まなくても、ソルバーの結果が常識的かどうかを表で確認できるようにする。
出力: reports/sanity_report.md（同じ内容を標準出力にも出す）

使い方: python3 scripts/sanity_report.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from harness_common import (  # noqa: E402
    ROOT, check_plan, iter_cases, load_config, load_master, solver_available,
)

MARK = {True: "OK", False: "**NG**", None: "未判定"}


def data_status(master):
    food = [i for i in master.values() if i["meal_role"] not in ("drink",)]
    with_protein = [i for i in food if "protein_per_unit" in i]
    return [
        f"- 品目数：{len(master)}",
        f"- たんぱく質の値が入っている食品：{len(with_protein)} / {len(food)}",
    ]


def build_report():
    master = load_master()
    config = load_config()
    lines = [
        "# 常識チェック報告",
        "",
        f"作成日：{date.today().isoformat()}",
        "",
        "## データの状態",
        "",
        *data_status(master),
        "",
    ]

    if not solver_available():
        lines += ["## ソルバーの結果", "", "solver パッケージが未実装のため、まだチェックできません。", ""]
        return "\n".join(lines), 0

    from solver import solve

    rows = []
    ng_count = 0
    for case in iter_cases(config):
        hh = case["household"]
        plan = solve(household=hh, template_id=case["template_id"], exclude_tags=[], exclude_ids=[])
        results = check_plan(plan, hh, case["template_id"], master, config)
        ngs = [f"{name}（{detail}）" for name, ok, detail in results if ok is False]
        ng_count += bool(ngs)
        juice = sum(e["count"] for e in plan["items"] if e["id"] == "V001")
        kinds = sum(1 for e in plan["items"] if e["count"] > 0)
        label = f"{case['template_id']} / 大人{hh['adults']} 子供{hh['children']} / {hh['days']}日"
        rows.append(f"| {label} | {kinds} | {juice} | {'OK' if not ngs else '**NG**'} | {'; '.join(ngs) or '—'} |")

    total = len(rows)
    lines += [
        "## ソルバーの結果",
        "",
        f"{total} 通りの世帯条件のうち、NG があったのは {ng_count} 通りです。",
        "",
        "| 条件 | 品目の種類数 | 野菜ジュースの本数 | 判定 | NG の内容 |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        "## 判定に使った閾値（tests/sanity_config.json）",
        "",
        f"- エネルギー：大人 {config['energy']['adult_kcal_per_day']} kcal/日、子供係数 {config['energy']['child_factor']}、"
        f"上限は目標の {config['energy']['max_ratio_to_target']} 倍",
        f"- 水：1人1日 {config['water']['ml_per_person_per_day']} ml",
        f"- 1品目の上限：1人1日あたり {config['per_item_caps']['max_units_per_person_day_by_role']}、"
        f"エネルギーの {config['per_item_caps']['max_kcal_share_of_total']:.0%} まで",
        f"- 多様性：{config['diversity']['min_distinct_items_by_role']}",
        "",
    ]
    return "\n".join(lines), ng_count


def main():
    report, ng_count = build_report()
    out = ROOT / "reports" / "sanity_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n→ {out.relative_to(ROOT)} に保存しました")
    return 1 if ng_count else 0


if __name__ == "__main__":
    sys.exit(main())
