"""公的な備蓄リストの例（data/reference_stock_lists.json）を品目マスタに当てはめ、
1人1日あたりのエネルギー（kcal）とたんぱく質（g）を計算する（Issue #17）。

- 候補の品目が複数ある項目は、kcal が最小になる当てはめと最大になる当てはめの両方を計算し、範囲で示す。
- map.tier が confirmed の項目だけの値と、reference（出典のない仮定を含む）も足した値を分けて示す。
- excluded の項目は計算に入れない。たんぱく質の値がない品目は 0g として足し、その品目を一覧に出す。

使い方:
    python3 scripts/reference_energy.py           # Markdown の表を標準出力に出す
    python3 scripts/reference_energy.py --json    # 計算結果を JSON で出す
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTS_PATH = ROOT / "data" / "reference_stock_lists.json"
MASTER_PATH = ROOT / "data" / "items-master.json"

ROLES = ("staple", "main", "side", "snack")
ROLE_LABELS = {"staple": "主食", "main": "主菜", "side": "副菜", "snack": "間食"}
TIER_SETS = {"confirmed": ("confirmed",), "with_reference": ("confirmed", "reference")}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def units_of(entry, item):
    quantity = entry["quantity"]
    if entry["map"]["basis"] == "weight":
        return quantity["grams"] / item["unit_gram"]
    return quantity["count"]


def candidate_values(entry, master):
    """候補ごとの (kcal, protein_g または None, 品目) を返す。"""
    values = []
    for item_id in entry["map"]["candidates"]:
        item = master[item_id]
        units = units_of(entry, item)
        protein = item.get("protein_per_unit")
        values.append((
            units * item["cal_per_unit"],
            None if protein is None else units * protein,
            item,
        ))
    return values


def evaluate(stock_list, master, tiers, pick):
    """pick は min か max。kcal でその候補を選んだときの合計を返す。"""
    household = stock_list["household"]
    if household.get("children"):
        raise ValueError(f"{stock_list['id']}: 子供を含む世帯の換算は未対応")
    person_days = household["adults"] * household["days"]

    kcal_by_role = {role: 0.0 for role in ROLES}
    protein = 0.0
    protein_missing = set()
    chosen = []
    for entry in stock_list["entries"]:
        if entry["map"]["tier"] not in tiers:
            continue
        kcal, entry_protein, item = pick(candidate_values(entry, master), key=lambda v: v[0])
        role = item["meal_role"]
        if role not in kcal_by_role:
            raise ValueError(f"{stock_list['id']}: 想定外の役割 {role}（{item['id']}）")
        kcal_by_role[role] += kcal
        if entry_protein is None:
            protein_missing.add(item["id"])
        else:
            protein += entry_protein
        chosen.append(item["id"])

    per_day = {role: kcal / person_days for role, kcal in kcal_by_role.items()}
    return {
        "kcal": sum(per_day.values()),
        "kcal_by_role": per_day,
        "protein_g": protein / person_days,
        "protein_missing_ids": sorted(protein_missing),
        "chosen_ids": chosen,
    }


def compute(stock_list, master):
    result = {"id": stock_list["id"], "household": stock_list["household"]}
    for name, tiers in TIER_SETS.items():
        result[name] = {
            "low": evaluate(stock_list, master, tiers, min),
            "high": evaluate(stock_list, master, tiers, max),
        }
    result["excluded"] = [e["original"] for e in stock_list["entries"] if e["map"]["tier"] == "excluded"]
    result["reference"] = [e["original"] for e in stock_list["entries"] if e["map"]["tier"] == "reference"]
    return result


def compute_all():
    master = {item["id"]: item for item in load_json(MASTER_PATH)["items"]}
    data = load_json(LISTS_PATH)
    computed = [compute(l, master) for l in data["lists"] if l["computable"]]
    stated = [l for l in data["lists"] if not l["computable"] and l.get("stated_values")]
    return data, computed, stated


def span(x, y, digits=0):
    # 役割ごとの値は、合計の kcal が最大になる当てはめのほうが小さいこともあるので並べ替える
    a, b = sorted((round(x, digits), round(y, digits)))
    fmt = f"{{:,.{digits}f}}"
    return fmt.format(a) if a == b else f"{fmt.format(a)}–{fmt.format(b)}"


def household_text(household):
    return f"大人{household['adults']}人・{household['days']}日"


def markdown(data, computed, stated):
    titles = {l["id"]: l for l in data["lists"]}
    out = [
        "### 1人1日あたり（範囲は、候補の品目のうち kcal が最小・最大になる当てはめ）",
        "",
        "| リスト | 対象 | kcal（確定分） | kcal（確定＋参考） | たんぱく質 g（確定＋参考） | 主食＋主菜 kcal | 副菜 kcal | 間食 kcal |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in computed:
        c, w = r["confirmed"], r["with_reference"]
        lo, hi = w["low"], w["high"]
        role = lambda *roles: span(sum(lo["kcal_by_role"][x] for x in roles),
                                   sum(hi["kcal_by_role"][x] for x in roles))
        out.append(
            f"| {r['id']} | {household_text(r['household'])} "
            f"| {span(c['low']['kcal'], c['high']['kcal'])} "
            f"| {span(lo['kcal'], hi['kcal'])} "
            f"| {span(lo['protein_g'], hi['protein_g'], 1)} "
            f"| {role('staple', 'main')} | {role('side')} | {role('snack')} |"
        )
    out += [
        "",
        "- 主食＋主菜・副菜・間食の列は「確定＋参考」の値。役割はマスタの `meal_role` による。",
        "- たんぱく質は kcal の当てはめに合わせた値（たんぱく質の最小・最大ではない）。",
        "",
        "### 役割ごとの内訳（1人1日あたり kcal）",
        "",
        "| リスト | 範囲 | " + " | ".join(
            f"{ROLE_LABELS[x]}（確定）" for x in ROLES) + " | " + " | ".join(
            f"{ROLE_LABELS[x]}（確定＋参考）" for x in ROLES) + " |",
        "| --- | --- |" + " ---: |" * (2 * len(ROLES)),
    ]
    for r in computed:
        for side, label in (("low", "最小"), ("high", "最大")):
            c = r["confirmed"][side]["kcal_by_role"]
            w = r["with_reference"][side]["kcal_by_role"]
            out.append(
                f"| {r['id']} | {label} | "
                + " | ".join(f"{c[x]:,.0f}" for x in ROLES) + " | "
                + " | ".join(f"{w[x]:,.0f}" for x in ROLES) + " |"
            )
    out += ["", "### たんぱく質の値がマスタにない品目（0g として計算）", ""]
    for r in computed:
        missing = sorted(set(r["with_reference"]["low"]["protein_missing_ids"])
                         | set(r["with_reference"]["high"]["protein_missing_ids"]))
        out.append(f"- {r['id']}：{'、'.join(missing) if missing else 'なし'}")
    out += ["", "### 計算から外した項目", ""]
    for r in computed:
        out.append(f"- {r['id']}（{len(r['excluded'])}件）：{' ／ '.join(r['excluded'])}")
    if stated:
        out += [
            "",
            "### 資料に書かれた値（再計算していない）",
            "",
            "| リスト | 対象 | 日 | kcal | たんぱく質 g |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for l in stated:
            for v in l["stated_values"]:
                out.append(f"| {l['id']} | {l['target_text']} | {v['day']} | {v['kcal']:,} | {v['protein_g']} |")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="計算結果を JSON で出す")
    args = parser.parse_args(argv)
    data, computed, stated = compute_all()
    if args.json:
        json.dump({"computed": computed}, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(markdown(data, computed, stated))


if __name__ == "__main__":
    main()
