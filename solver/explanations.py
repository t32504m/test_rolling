"""Deterministic Japanese explanations of the solved quantities, not advice."""

ROLE_NAMES = {"staple": "主食", "main": "主菜", "side": "副菜", "snack": "間食"}


def number(value):
    """Avoid exposing floating-point representation noise in prose."""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def explain_plan(counts, pool, config, adults, children, infants, days,
                 target_kcal, target_protein, ideals, required_water, tolerance):
    meals_cfg = config["meals"]
    meal_count = meals_cfg["per_person_per_day"] * (adults + children) * days
    foods = {i: item for i, (item, _) in pool.items()
             if item["daily_coeff"] is None and item["meal_role"] != "drink"}
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
        meal_details[role] = (
            f"{label}の目安は {number(meals_cfg['per_person_per_day'])}食 × "
            f"（大人{adults}＋子供{children}）× {days}日 × {number(per_meal)}食分"
            f"＝{number(allowed)}食分（乳幼児{infants}人は含めない）。"
            f"役割全体では{number(got)}食分、選択品目の購入丸め許容は"
            f"Σ（購入単位－1）÷1食分の量＝{number(rounding)}食分。"
        )
        if extra > tolerance:
            reason = (
                f"{label}の目安{number(allowed)}食分と購入丸め許容{number(rounding)}食分に対し、"
                f"{number(got)}食分を選び、超過は{number(extra)}食分。"
                f"候補・除外・1品目の上限・多様性を守り、{nutrition_targets}を満たすため、"
                "副菜・間食による補完も含め、主食・主菜の超過食数の合計を最小化した結果。"
            )
            meal_extras[role] = {"servings": extra, "reason": reason}

    base_kcal = sum(foods[i]["cal_per_unit"] * count for i, count in counts.items()
                    if i in foods and foods[i]["meal_role"] in meals_cfg["max_servings_per_meal_by_role"])
    shortfall = max(0, target_kcal - base_kcal)
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
                reason = (
                    f"{ROLE_NAMES.get(role, role)}：主食・主菜{number(base_kcal)} kcalと"
                    f"目標{number(target_kcal)} kcalとの差{number(shortfall)} kcalを、"
                    "副菜・間食で補う構成。"
                )
            reason += (
                f"本品の理想量は重み{number(weight)} × 1食分{number(serving)}{unit} × "
                f"目標{number(target_kcal)} kcal ÷ 候補の重み付き合計{number(preferred_kcal)} kcal"
                f"＝{number(ideals[item_id])}{unit}。"
                f"食数超過の最小値・栄養・偏り・多様性を守って好みからのずれを最小化し、"
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
