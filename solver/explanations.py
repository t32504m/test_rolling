"""Deterministic Japanese explanations of the solved quantities, not advice."""

import math

ROLE_NAMES = {"staple": "主食", "main": "主菜", "side": "副菜", "snack": "間食"}


def number(value):
    """Avoid exposing floating-point representation noise in prose."""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _infant_rationale(item_id, item, count, infants, days, infant_days, milk_names):
    """Plain words for parents: daily amount, number of days, and the milk choice."""
    unit = item["consume_unit"]
    raw = item["daily_coeff"] * infants * infant_days
    text = (f"乳幼児{infants}人に、1人1日{number(item['daily_coeff'])}{unit} × "
            f"{infant_days}日分＝{number(raw)}{unit}")
    text += "。" if abs(count - raw) < 1e-9 else f"なので、{count}{unit}。"
    if infant_days > days:
        text += (f"農林水産省が乳児用などの特殊食品は少なくとも2週間分の備蓄を勧めているため、"
                 f"世帯の{days}日分ではなく{infant_days}日分にした。")
    preferred = next(iter(milk_names), None)
    if item_id in milk_names and item_id != preferred:
        text += f"{milk_names[preferred]}を外したので、{item['name']}にした。"
    return text


def explain_plan(counts, pool, config, adults, children, infants, days,
                 target_kcal, target_protein, ideals, required_water, tolerance,
                 milk_names=None, infant_days=None):
    milk_names = milk_names or {}
    meals_cfg = config["meals"]
    meal_count = meals_cfg["per_person_per_day"] * (adults + children) * days
    foods = {i: item for i, (item, _) in pool.items()
             if item["daily_coeff"] is None and item["meal_role"] != "drink"}
    upper_cfg = meals_cfg.get("upper_servings_per_meal_by_role", {})
    meal_extras, meal_details = {}, {}
    nutrition_targets = f"エネルギー {number(target_kcal)} kcal"
    if target_protein is not None:
        nutrition_targets += f"・既知たんぱく質 {number(target_protein)} g 以上"
    for role, per_meal in meals_cfg["max_servings_per_meal_by_role"].items():
        chosen = [i for i in counts if i in foods and foods[i]["meal_role"] == role]
        got = sum(counts[i] / (foods[i].get("units_per_serving") or 1) for i in chosen)
        rounding = sum((foods[i]["pack_size"] - 1) / (foods[i].get("units_per_serving") or 1)
                       for i in chosen)
        allowed = meal_count * per_meal
        extra = max(0, got - allowed - rounding)
        label = ROLE_NAMES.get(role, role)
        upper = upper_cfg.get(role)
        upper_text = (f"上限は1食に{number(upper)}食分＝{number(meal_count * upper)}食分"
                      if upper is not None else "")
        meal_details[role] = (
            f"{label}の目安は {number(meals_cfg['per_person_per_day'])}食 × "
            f"（大人{adults}＋子供{children}）× {days}日 × {number(per_meal)}食分"
            f"＝{number(allowed)}食分（乳幼児{infants}人は含めない）。"
            f"役割全体では{number(got)}食分、選択品目の購入丸め許容は"
            f"Σ（購入単位－1）÷1食分の量＝{number(rounding)}食分。"
            + (f"{upper_text}（購入丸め分を除く）。" if upper_text else "")
        )
        if extra > tolerance:
            reason = (
                f"{label}の目安{number(allowed)}食分と購入丸め許容{number(rounding)}食分に対し、"
                f"{number(got)}食分を選び、超過は{number(extra)}食分。"
                f"エネルギーの不足を、間食ではなく{label}で補った。"
                f"候補・除外・1品目の上限・多様性を守り、{nutrition_targets}を満たし、"
                "テンプレートの好みからのずれを最小にしたうえで、主食・主菜の超過食数の合計を最小化した結果。"
            )
            meal_extras[role] = {"servings": extra, "reason": reason}

    preferred_kcal = sum(item["cal_per_unit"] * pool[i][1] * (item.get("units_per_serving") or 1)
                         for i, item in foods.items())
    basis_counts = {"all": adults + children + infants, "adults": adults,
                    "children": children, "infants": infants}
    basis_labels = {"all": "大人＋子供＋乳幼児", "adults": "大人", "children": "子供", "infants": "乳幼児"}
    rationale = {}
    for item_id in sorted(counts):
        item, weight = pool[item_id]
        count, unit, pack = counts[item_id], item["consume_unit"], item["pack_size"]
        if item["meal_role"] == "drink":
            water = config["water"]
            rationale[item_id] = (
                f"水：{number(water['ml_per_person_per_day'] / 1000)} L × "
                f"（大人{adults}＋子供{number(water['child_factor'])}×{children}"
                f"＋乳幼児{number(water['infant_factor'])}×{infants}）×{days}日"
                f"＝{number(required_water / 1000)} L。"
                f"1本{number(item['water_per_unit'] / 1000)} Lで必要量以上に切り上げ、"
                f"{count}{unit}＝{number(count * item['water_per_unit'] / 1000)} L。ケース単位には丸めない。"
            )
        elif item.get("coeff_basis") == "infants" and infant_days:
            rationale[item_id] = _infant_rationale(item_id, item, count, infants, days,
                                                   infant_days, milk_names)
        elif item["daily_coeff"] is not None:
            basis = item.get("coeff_basis") or "all"
            raw = item["daily_coeff"] * basis_counts[basis] * days
            rationale[item_id] = (
                f"特別食：{basis_labels[basis]}{basis_counts[basis]}人 × "
                f"1人1日{number(item['daily_coeff'])}{unit} × {days}日＝{number(raw)}{unit}。"
                f"購入単位{pack}{unit}へ切り上げ、{pack}×{count // pack}＝{count}{unit}。"
                "普通の食事のエネルギー・たんぱく質には加算しない。"
            )
        else:
            role = item["meal_role"]
            serving = item.get("units_per_serving") or 1
            if role in meal_details:
                reason = meal_details[role]
                if role in meal_extras:
                    reason += meal_extras[role]["reason"]
            else:
                # Pack rounding above the preferred amount still counts as "as preferred".
                if count <= math.ceil(ideals[item_id] - tolerance) + pack - 1:
                    reason = (
                        f"{ROLE_NAMES.get(role, role)}：テンプレートの好みの量のとおり。"
                        "エネルギーの不足は主食で補い、副菜・間食を好みの量より増やして埋めない。"
                    )
                else:
                    reason = (
                        f"{ROLE_NAMES.get(role, role)}：好みの量より多い。{nutrition_targets}・"
                        "主食と主菜の上限・1品目の上限・多様性を守り、全品目の好みからのずれ（kcal）の"
                        "合計を最小にすると、ほかの品目の購入単位との組み合わせで、この数になった。"
                    )
            reason += (
                f"本品の理想量は重み{number(weight)} × 1食分{number(serving)}{unit} × "
                f"目標{number(target_kcal)} kcal ÷ 候補の重み付き合計{number(preferred_kcal)} kcal"
                f"＝{number(ideals[item_id])}{unit}。"
                f"栄養・偏り・多様性・主食と主菜の上限を守って、まず好みからのずれを最小化し、"
                f"購入単位{pack}{unit}×{count // pack}＝{count}{unit}"
                f"（{number(count / serving)}食分）を選択。"
                f"{number(item['cal_per_unit'])} kcal×{count}＝"
                f"{number(item['cal_per_unit'] * count)} kcal。"
            )
            protein = item.get("protein_per_unit")
            if protein is None:
                reason += "たんぱく質は未入力のため下限計算では0g。"
            else:
                reason += f"既知たんぱく質{number(protein)} g×{count}＝{number(protein * count)} g。"
            rationale[item_id] = reason
    return rationale, meal_extras
