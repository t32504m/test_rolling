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
    ROOT, check_plan, iter_cases, load_config, load_master, servings, solver_available,
)

MARK = {True: "OK", False: "**NG**", None: "未判定"}
# 「なぜこの数なのか」を表で示す例の世帯（実験で主に使う条件）
EXAMPLE = {"household": {"adults": 2, "children": 1, "infants": 0, "days": 3}, "template_id": "standard"}


def household_label(hh):
    label = f"大人{hh['adults']} 子供{hh['children']}"
    if hh.get("infants"):
        label += f" 乳幼児{hh['infants']}"
    return f"{label} / {hh['days']}日"


def staple_vs_meals(plan, hh, master, config):
    meals = config["meals"]["per_person_per_day"] * (hh["adults"] + hh["children"]) * hh["days"]
    got = sum(servings(master[e["id"]], e["count"]) for e in plan["items"]
              if master[e["id"]]["meal_role"] == "staple")
    return f"{got:g} / {meals}"


def example_section(solve, master, config):
    hh, template_id = EXAMPLE["household"], EXAMPLE["template_id"]
    plan = solve(household=hh, template_id=template_id, exclude_tags=[], exclude_ids=[])
    rationale = plan.get("meta", {}).get("rationale") or {}
    rows = [f"| {master[e['id']]['name']} | {e['count']} {master[e['id']]['consume_unit']} | "
            f"{rationale.get(e['id'], '（説明がない）')} |"
            for e in plan["items"] if e["count"] > 0]
    extras = plan.get("meta", {}).get("meal_extras") or {}
    extra_lines = [f"- {role}：{info.get('reason', '')}" for role, info in extras.items()]
    return [
        f"## 例：{template_id} / {household_label(hh)} の内訳と根拠",
        "",
        "| 品目 | 数 | 根拠 |",
        "| --- | --- | --- |",
        *rows,
        "",
        *(["食事の回数を超えて追加したもの：", "", *extra_lines, ""] if extra_lines else []),
    ]


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
        label = f"{case['template_id']} / {household_label(hh)}"
        staple = staple_vs_meals(plan, hh, master, config)
        rows.append(f"| {label} | {kinds} | {staple} | {juice} | {'OK' if not ngs else '**NG**'} | {'; '.join(ngs) or '—'} |")

    total = len(rows)
    lines += [
        "## ソルバーの結果",
        "",
        f"{total} 通りの世帯条件のうち、NG があったのは {ng_count} 通りです。",
        "",
        "「主食 / 食事」は、主食の食数と食事の回数（3食 × 大人と子供の人数 × 日数）です。",
        "",
        "| 条件 | 品目の種類数 | 主食 / 食事 | 野菜ジュースの本数 | 判定 | NG の内容 |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        *example_section(solve, master, config),
        "## 判定に使った閾値（tests/sanity_config.json）",
        "",
        f"- エネルギー：大人 {config['energy']['adult_kcal_per_day']} kcal/日、子供係数 {config['energy']['child_factor']}、"
        f"上限は目標の {config['energy']['max_ratio_to_target']} 倍",
        f"- 水：1人1日 {config['water']['ml_per_person_per_day']} ml（子供 {config['water']['child_factor']} 倍、"
        f"乳幼児 {config['water']['infant_factor']} 倍）",
        f"- 食事の回数：1人1日 {config['meals']['per_person_per_day']} 食。1食あたり "
        f"{config['meals']['max_servings_per_meal_by_role']}（超える場合は理由が必要）",
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
