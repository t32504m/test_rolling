"""Diet problem model. Nutrition and sanity limits come from repository data.

Counts are consumption units; food is rounded to purchase packs, whereas water
is sized in bottles, consistently with planner.html's required-volume policy.
"""

import json
import math
from collections.abc import Mapping
from pathlib import Path

import pulp

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1e-6  # Numerical solver tolerance, not a nutrition threshold.


class InfeasiblePlanError(ValueError):
    """The permitted items cannot meet the household's hard constraints."""


def _read(relative):
    with (ROOT / relative).open(encoding="utf-8") as stream:
        return json.load(stream)


def _household(household):
    if not isinstance(household, Mapping):
        raise ValueError("household must contain adults, children and days")
    values = []
    for key in ("adults", "children", "days"):
        value = household.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
        values.append(value)
    adults, children, days = values
    if days == 0 or adults + children == 0:
        raise ValueError("days and the total number of people must be positive")
    return adults, children, days


def _pool(master, template_id, exclude_tags, exclude_ids):
    tags, ids = set(exclude_tags or ()), set(exclude_ids or ())
    if template_id is None:
        weights = dict.fromkeys(master, 1)
    else:
        templates = {entry["id"]: entry for entry in _read("templates/index.json")}
        if template_id not in templates:
            raise ValueError(f"unknown template_id: {template_id!r}")
        template = _read(f"templates/{templates[template_id]['file']}")
        tags.update(template.get("exclude_tags", ()))
        weights = {entry["ref"]: entry["weight"] for entry in template["items"]}
    for item_id, weight in weights.items():
        if not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"{item_id}: template weight must be finite and positive")
    return {
        item_id: (master[item_id], weights[item_id])
        for item_id in sorted(weights)
        if item_id not in ids and not tags.intersection(master[item_id]["tags"])
    }


def _water(pool, required_ml):
    # Water is required volume, not whole cases: rounding W004 to its 12-bottle
    # case would violate the agreed water-overstock bound for small households.
    choices = []
    for item_id, (item, weight) in pool.items():
        if item["meal_role"] == "drink" and item["water_per_unit"] > 0:
            unit = item["water_per_unit"]
            count = math.ceil(required_ml / unit)
            choices.append((count * unit - required_ml, -weight, count, item_id))
    if not choices:
        raise InfeasiblePlanError("no drinking water remains after exclusions")
    _, _, count, item_id = min(choices)
    return item_id, count


def _optimize(problem, objective, phase):
    problem.setObjective(objective)
    # Stable variable order, pinned CBC, one thread and fixed seeds make repeated
    # experiments reproducible. Never return an unproven/partial solution.
    status = problem.solve(pulp.PULP_CBC_CMD(
        msg=False, threads=1, timeLimit=30, gapRel=0, gapAbs=0,
        options=["randomSeed 1", "randomCbcSeed 1"],
    ))
    if status == pulp.LpStatusInfeasible:
        raise InfeasiblePlanError(f"no plan satisfies the hard constraints ({phase})")
    if status != pulp.LpStatusOptimal or problem.sol_status != pulp.LpSolutionOptimal:
        raise RuntimeError(f"CBC did not prove an optimal solution ({phase})")
    return pulp.value(objective)


def solve(household, template_id=None, exclude_tags=None, exclude_ids=None):
    """Return {items: [{id, count}], meta: {...}} or raise InfeasiblePlanError.

    All nutrition targets and caps are loaded from tests/sanity_config.json.
    Incomplete protein data disables the *whole* protein constraint, explicitly
    reported in meta; missing values are never treated as zero or invented.
    """
    adults, children, days = _household(household)
    people_days = (adults + children) * days
    master = {item["id"]: item for item in _read("data/items-master.json")["items"]}
    config = _read("tests/sanity_config.json")
    pool = _pool(master, template_id, exclude_tags, exclude_ids)
    water_id, water_count = _water(pool, config["water"]["ml_per_person_per_day"] * people_days)
    foods = {i: pair for i, pair in pool.items()
             if pair[0]["daily_coeff"] is None and pair[0]["meal_role"] != "drink"}
    if not foods or not any(item["cal_per_unit"] > 0 for item, _ in foods.values()):
        raise InfeasiblePlanError("no energy-providing food remains after exclusions")

    energy = config["energy"]
    target_kcal = energy["adult_kcal_per_day"] * (adults + energy["child_factor"] * children) * days
    upper_kcal = target_kcal * energy["max_ratio_to_target"]
    caps = config["per_item_caps"]
    problem = pulp.LpProblem("rolling_stock", pulp.LpMinimize)
    counts, selected = {}, {}
    for item_id, (item, _) in foods.items():
        pack = item["pack_size"]
        role_cap = caps["max_units_per_person_day_by_role"].get(item["meal_role"])
        if role_cap is not None:
            # Round the per-person allowance up to the next purchase pack.
            max_packs = math.ceil(role_cap * people_days / pack)
        elif item["cal_per_unit"] > 0:
            max_packs = math.floor(upper_kcal / (item["cal_per_unit"] * pack))
        else:
            raise ValueError(f"{item_id}: no per-person cap for a zero-energy food")
        packs = pulp.LpVariable(f"packs_{item_id}", 0, max_packs, cat="Integer")
        counts[item_id] = pack * packs
        selected[item_id] = pulp.LpVariable(f"chosen_{item_id}", cat="Binary")
        problem += packs >= selected[item_id]
        problem += packs <= max_packs * selected[item_id]

    total_kcal = pulp.lpSum(foods[i][0]["cal_per_unit"] * count for i, count in counts.items())
    problem += total_kcal >= target_kcal
    problem += total_kcal <= upper_kcal
    for item_id, (item, _) in foods.items():
        problem += item["cal_per_unit"] * counts[item_id] <= caps["max_kcal_share_of_total"] * total_kcal
    for role, minimum in config["diversity"]["min_distinct_items_by_role"].items():
        available = [i for i, (item, _) in foods.items() if item["meal_role"] == role]
        problem += pulp.lpSum(selected[i] for i in available) >= min(minimum, len(available))

    missing_protein = [i for i, (item, _) in foods.items() if item.get("protein_per_unit") is None]
    protein_active = not missing_protein
    target_protein = None
    if protein_active:
        protein = config["protein"]
        target_protein = protein["adult_g_per_day"] * (adults + protein["child_factor"] * children) * days
        problem += pulp.lpSum(foods[i][0]["protein_per_unit"] * count for i, count in counts.items()) >= target_protein

    # Template weights express relative servings. Convert those servings to
    # units, scale to the energy target, and minimize absolute energy deviations
    # from that preferred mix. Nutrition/caps/diversity always take precedence.
    preferred_units = {i: weight * (item.get("units_per_serving") or 1)
                       for i, (item, weight) in foods.items()}
    preferred_kcal = sum(foods[i][0]["cal_per_unit"] * units for i, units in preferred_units.items())
    deviations, ideals = [], {}
    for item_id, (item, _) in foods.items():
        ideal = preferred_units[item_id] * target_kcal / preferred_kcal
        ideals[item_id] = ideal
        delta = pulp.LpVariable(f"deviation_{item_id}", lowBound=0)
        problem += delta >= counts[item_id] - ideal
        problem += delta >= ideal - counts[item_id]
        # Keep zero-calorie foods bounded/preferences meaningful as well.
        deviations.append(max(item["cal_per_unit"], 1) * delta)
    preference_error = pulp.lpSum(deviations)
    _optimize(problem, preference_error, "template preference")
    # CBC serializes continuous values with limited decimal precision. Evaluate
    # the incumbent from integer counts rather than those rounded deviations
    # before fixing the first objective for the lexicographic second phase.
    optimum = sum(max(foods[i][0]["cal_per_unit"], 1)
                  * abs(round(pulp.value(counts[i])) - ideals[i]) for i in foods)
    problem += preference_error <= optimum + TOLERANCE
    _optimize(problem, total_kcal, "minimum energy excess")

    quantities = {water_id: water_count}
    for item_id, count in counts.items():
        value = pulp.value(count)
        rounded = round(value)
        if abs(value - rounded) > TOLERANCE:
            raise RuntimeError(f"CBC returned a nonintegral count for {item_id}")
        if rounded:
            quantities[item_id] = rounded
    # Special foods are supplementary, not a replacement for normal food.
    # Only an explicit template opts into them; unrestricted selection must not
    # presume infant care, dysphagia or supplementation needs for every person.
    if template_id is not None:
        for item_id, (item, _) in pool.items():
            if item["daily_coeff"] is not None:
                basis = {"all": adults + children, "adults": adults, "children": children}
                basis_name = item.get("coeff_basis") or "all"
                if basis_name not in basis:
                    raise ValueError(f"{item_id}: unknown coeff_basis {basis_name!r}")
                count = math.ceil(item["daily_coeff"] * basis[basis_name] * days / item["pack_size"]) * item["pack_size"]
                if count:
                    quantities[item_id] = count

    actual_kcal = sum(foods[i][0]["cal_per_unit"] * quantities.get(i, 0) for i in foods)
    # Reject numeric feasibility-tolerance violations instead of silently
    # reporting a plan just below an agreed nutrition target.
    if not target_kcal <= actual_kcal <= upper_kcal:
        raise RuntimeError("CBC solution violates the energy bounds after rounding")
    total_protein = (sum(foods[i][0]["protein_per_unit"] * quantities.get(i, 0) for i in foods)
                     if protein_active else None)
    if protein_active and total_protein < target_protein:
        raise RuntimeError("CBC solution violates the protein target after rounding")
    return {
        "items": [{"id": i, "count": quantities[i]} for i in sorted(quantities)],
        "meta": {
            "status": "optimal",
            "template_id": template_id,
            "target_kcal": target_kcal,
            "total_kcal": actual_kcal,
            "water_ml": master[water_id]["water_per_unit"] * water_count,
            "protein_constraint": "active" if protein_active else "missing_data",
            "missing_protein_ids": missing_protein,
            "target_protein_g": target_protein,
            "total_protein_g": total_protein,
            "thresholds": "tests/sanity_config.json",
        },
    }
