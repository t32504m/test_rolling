"""テストと常識チェック報告で共有する、データの読み込みと判定の処理。

判定の閾値はすべて tests/sanity_config.json から読む。ここに数値を直接書かない。
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# solver パッケージ（リポジトリ直下）を、どこから実行しても import できるようにする
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 食数の配分対象となる役割。drink（水）と special（乳児用ミルク等の人日係数型）は別扱い
MEAL_ROLES = ("staple", "main", "side", "snack")

# 浮動小数点の計算誤差だけを吸収するための許容幅（栄養の閾値ではない）。
# 例：2000 × (1 + 0.8 × 3) × 7 は 47600.00000000001 になり、ちょうど 47600 kcal の解を不合格にしてしまう
FLOAT_TOLERANCE = 1e-6


def load_json(rel_path):
    with open(ROOT / rel_path, encoding="utf-8") as f:
        return json.load(f)


def load_master():
    return {item["id"]: item for item in load_json("data/items-master.json")["items"]}


def load_template_index():
    return load_json("templates/index.json")


def load_template(template_id):
    for entry in load_template_index():
        if entry["id"] == template_id:
            return load_json(f"templates/{entry['file']}")
    raise KeyError(template_id)


def load_config():
    return load_json("tests/sanity_config.json")


def solver_available():
    return importlib.util.find_spec("solver") is not None


def iter_cases(config):
    cases = config["cases"]
    for template in load_template_index():
        for adults in cases["adults"]:
            for children in cases["children"]:
                for days in cases["days"]:
                    yield {
                        "household": {"adults": adults, "children": children, "days": days},
                        "template_id": template["id"],
                    }


def check_plan(plan, household, template_id, master, config, exclude_tags=(), exclude_ids=()):
    """解（plan）に対する常識チェックを行い、[(チェック名, 合否, 詳細)] を返す。"""
    results = []
    adults, children, days = household["adults"], household["children"], household["days"]
    people = adults + children
    items = plan.get("items", [])
    counts = {}

    # 形式：マスタに存在する品目、0以上の整数
    form_ok = True
    form_detail = []
    for entry in items:
        item_id, count = entry.get("id"), entry.get("count")
        if item_id not in master:
            form_ok = False
            form_detail.append(f"マスタにない品目 {item_id}")
            continue
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            form_ok = False
            form_detail.append(f"{item_id} の数量が0以上の整数でない（{count!r}）")
            continue
        counts[item_id] = counts.get(item_id, 0) + count
    results.append(("形式（マスタにある品目・0以上の整数）", form_ok, "; ".join(form_detail) or "OK"))

    chosen = {i: c for i, c in counts.items() if c > 0}

    # 除外：テンプレートと引数の除外タグ・除外品目が含まれていない
    tags_to_exclude = set(exclude_tags)
    if template_id is not None:
        tags_to_exclude |= set(load_template(template_id).get("exclude_tags", []))
    violated = [i for i in chosen
                if i in set(exclude_ids) or tags_to_exclude & set(master[i]["tags"])]
    results.append(("除外した品目が入っていない", not violated,
                    f"違反: {', '.join(violated)}" if violated else "OK"))

    # エネルギー：通常の食品（人日係数型の特別食を除く）で目標の範囲に入る
    energy_cfg = config["energy"]
    eff_people_e = adults + energy_cfg["child_factor"] * children
    target_kcal = energy_cfg["adult_kcal_per_day"] * eff_people_e * days
    food_ids = [i for i in chosen if master[i]["daily_coeff"] is None]
    total_kcal = sum(master[i]["cal_per_unit"] * chosen[i] for i in food_ids)
    upper = target_kcal * energy_cfg["max_ratio_to_target"]
    results.append(("エネルギーが目標以上", total_kcal + FLOAT_TOLERANCE >= target_kcal,
                    f"{total_kcal:.0f} / 目標 {target_kcal:.0f} kcal"))
    results.append(("エネルギーが過剰でない", total_kcal <= upper + FLOAT_TOLERANCE,
                    f"{total_kcal:.0f} / 上限 {upper:.0f} kcal"))

    # たんぱく質：値のない品目は 0g とみなす（オーナー承認 2026-10-22）。
    # 「目標以上」の判定なので、実際の値（0g 以上）で計算しても必ず合格する、安全側の扱いになる。
    # 品目マスタにたんぱく質の値が1件もない場合だけ判定しない（None を返す）
    protein_cfg = config["protein"]
    if any("protein_per_unit" in item for item in master.values()) and food_ids:
        eff_people_p = adults + protein_cfg["child_factor"] * children
        target_p = protein_cfg["adult_g_per_day"] * eff_people_p * days
        total_p = sum((master[i].get("protein_per_unit") or 0) * chosen[i] for i in food_ids)
        unknown = [i for i in food_ids if master[i].get("protein_per_unit") is None]
        note = f"（値のない {len(unknown)} 品目は 0g として計算）" if unknown else ""
        results.append(("たんぱく質が目標以上", total_p + FLOAT_TOLERANCE >= target_p,
                        f"{total_p:.0f} / 目標 {target_p:.0f} g{note}"))
    else:
        results.append(("たんぱく質が目標以上", None, "品目マスタに protein_per_unit が1件もない"))

    # 水：必要量以上で、最大の水の1単位分を超えて過剰でない
    need_ml = config["water"]["ml_per_person_per_day"] * people * days
    water_ids = [i for i in chosen if master[i]["meal_role"] == "drink"]
    total_ml = sum(master[i]["water_per_unit"] * chosen[i] for i in water_ids)
    max_unit = max((master[i]["water_per_unit"] for i in water_ids), default=0)
    water_ok = need_ml <= total_ml < need_ml + max(max_unit, 1)
    results.append(("水が必要量どおり（不足も過剰もない）", water_ok,
                    f"{total_ml / 1000:.1f} L / 必要 {need_ml / 1000:.1f} L"))

    # 1品目の上限：1人1日あたりの量と、全エネルギーに占める割合
    caps = config["per_item_caps"]
    over = []
    for i in food_ids:
        role = master[i]["meal_role"]
        per_day_cap = caps["max_units_per_person_day_by_role"].get(role)
        if per_day_cap is not None:
            limit = per_day_cap * max(people, 1) * days + master[i]["pack_size"]
            if chosen[i] > limit:
                over.append(f"{master[i]['name']} {chosen[i]}個（上限 {limit:.0f}）")
        if total_kcal > 0:
            share = master[i]["cal_per_unit"] * chosen[i] / total_kcal
            if share > caps["max_kcal_share_of_total"]:
                over.append(f"{master[i]['name']} がエネルギーの {share:.0%}")
    results.append(("1品目に偏っていない", not over, "; ".join(over) or "OK"))

    # 多様性：役割ごとに異なる品目が最低数ある（選べる品目数が上限）
    div_cfg = config["diversity"]["min_distinct_items_by_role"]
    if template_id is not None:
        pool = [ref["ref"] for ref in load_template(template_id)["items"]]
    else:
        pool = list(master)
    pool = [i for i in pool
            if i not in set(exclude_ids) and not (tags_to_exclude & set(master[i]["tags"]))]
    short = []
    for role, minimum in div_cfg.items():
        available = len({i for i in pool if master[i]["meal_role"] == role})
        got = len({i for i in chosen if master[i]["meal_role"] == role})
        need = min(minimum, available)
        if got < need:
            short.append(f"{role}: {got}品目（最低 {need}）")
    results.append(("品目に多様性がある", not short, "; ".join(short) or "OK"))

    return results
