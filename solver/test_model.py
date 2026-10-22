"""Additional solver tests; synthetic nutrients never modify the food master.

Run with: python3 -m unittest solver.test_model -v
"""

import copy
import math
import unittest
from unittest.mock import patch

from solver import InfeasiblePlanError, solve
from solver import model


class SolverModelTest(unittest.TestCase):
    household = {"adults": 2, "children": 1, "days": 3}

    def with_protein(self, per_kcal):
        master = copy.deepcopy(model._read("data/items-master.json"))
        for item in master["items"]:
            item["protein_per_unit"] = per_kcal * item["cal_per_unit"]
        original_read = model._read
        return patch.object(model, "_read", side_effect=lambda path:
                            master if path == "data/items-master.json" else original_read(path))

    def test_complete_protein_data_activates_constraint(self):
        config = model._read("tests/sanity_config.json")
        # Artificial data with ample protein; no nutritional claim is made.
        per_kcal = 2 * config["protein"]["adult_g_per_day"] / config["energy"]["adult_kcal_per_day"]
        with self.with_protein(per_kcal):
            meta = solve(self.household, "standard")["meta"]
        self.assertEqual(meta["protein_constraint"], "active")
        self.assertEqual(meta["missing_protein_ids"], [])
        self.assertGreaterEqual(meta["total_protein_g"], meta["target_protein_g"])

    def test_impossible_protein_target_is_not_silently_ignored(self):
        with self.with_protein(0):
            with self.assertRaises(InfeasiblePlanError):
                solve(self.household, "standard")

    def test_partial_protein_data_is_a_conservative_lower_bound(self):
        config = model._read("tests/sanity_config.json")
        per_kcal = 2 * config["protein"]["adult_g_per_day"] / config["energy"]["adult_kcal_per_day"]
        original_read = model._read
        master = copy.deepcopy(original_read("data/items-master.json"))
        for item in master["items"]:
            item["protein_per_unit"] = per_kcal * item["cal_per_unit"]
        next(item for item in master["items"] if item["id"] == "S002")["protein_per_unit"] = None
        next(item for item in master["items"] if item["id"] == "M006").pop("protein_per_unit")
        with patch.object(model, "_read", side_effect=lambda path:
                          master if path == "data/items-master.json" else original_read(path)):
            plan = solve(self.household, "standard")
        meta = plan["meta"]
        self.assertEqual(meta["protein_constraint"], "active")
        self.assertEqual(meta["protein_assumed_zero_ids"], ["M006", "S002"])
        by_id = {item["id"]: item for item in master["items"]}
        expected = sum((by_id[item["id"]].get("protein_per_unit") or 0) * item["count"]
                       for item in plan["items"] if by_id[item["id"]]["daily_coeff"] is None)
        self.assertEqual(meta["total_protein_g"], expected)
        self.assertGreaterEqual(meta["total_protein_g"] + model.TOLERANCE, meta["target_protein_g"])

    def test_partial_data_does_not_disable_an_infeasible_constraint(self):
        original_read = model._read
        master = copy.deepcopy(original_read("data/items-master.json"))
        for item in master["items"]:
            item.pop("protein_per_unit", None)
        # A known value outside the candidate pool still enables the constraint:
        # filtering must not silently turn an impossible protein target off.
        next(item for item in master["items"] if item["id"] == "S001")["protein_per_unit"] = 0
        with patch.object(model, "_read", side_effect=lambda path:
                          master if path == "data/items-master.json" else original_read(path)):
            with self.assertRaises(InfeasiblePlanError):
                solve(self.household, "standard")

    def test_only_a_master_without_protein_values_disables_constraint(self):
        original_read = model._read
        master = copy.deepcopy(original_read("data/items-master.json"))
        for index, item in enumerate(master["items"]):
            if index % 2:
                item.pop("protein_per_unit", None)
            else:
                item["protein_per_unit"] = None
        with patch.object(model, "_read", side_effect=lambda path:
                          master if path == "data/items-master.json" else original_read(path)):
            meta = solve(self.household, "standard")["meta"]
        self.assertEqual(meta["protein_constraint"], "missing_data")
        self.assertTrue(meta["missing_protein_ids"])
        self.assertEqual(meta["protein_assumed_zero_ids"], [])
        self.assertIsNone(meta["total_protein_g"])

    def test_roundoff_at_energy_and_protein_boundaries(self):
        # Artificial equal foods force exactly one unit of each through the
        # diversity/energy bounds. This exercises the real CBC + final checks.
        original_read = model._read
        config = original_read("tests/sanity_config.json")
        household = {"adults": 1, "children": 3, "days": 7}
        energy = config["energy"]
        target = energy["adult_kcal_per_day"] * (1 + energy["child_factor"] * 3) * 7
        protein = config["protein"]
        protein_target = protein["adult_g_per_day"] * (1 + protein["child_factor"] * 3) * 7
        for boundary in ("lower", "upper"):
            with self.subTest(boundary=boundary):
                cfg = copy.deepcopy(config)
                if boundary == "upper":
                    cfg["energy"]["adult_kcal_per_day"] = math.nextafter(energy["adult_kcal_per_day"], 0)
                total = round(target if boundary == "lower" else target * energy["max_ratio_to_target"])
                foods = [
                    {"id": f"TEST{i}", "meal_role": role, "tags": [], "daily_coeff": None,
                     "cal_per_unit": total / 4, "protein_per_unit": round(protein_target, 6) / 4,
                     "pack_size": 1, "units_per_serving": 1, "consume_unit": "個"}
                    for i, role in enumerate(("staple", "staple", "main", "main"))
                ]
                water = next(item for item in original_read("data/items-master.json")["items"]
                             if item["id"] == "W004")
                def read(path):
                    if path == "data/items-master.json":
                        return {"items": foods + [water]}
                    if path == "tests/sanity_config.json":
                        return cfg
                    return original_read(path)
                with patch.object(model, "_read", side_effect=read):
                    plan = solve(household)
                self.assertEqual(plan["meta"]["total_kcal"], total)
                self.assertEqual(plan["meta"]["total_protein_g"], round(protein_target, 6))

    def test_infeasible_exclusions_do_not_restore_forbidden_food(self):
        master = model._read("data/items-master.json")["items"]
        forbidden = [item["id"] for item in master if item["meal_role"] != "drink"]
        with self.assertRaises(InfeasiblePlanError):
            solve(self.household, None, exclude_ids=forbidden)

    def test_water_exclusion_is_not_ignored(self):
        with self.assertRaises(InfeasiblePlanError):
            solve(self.household, "standard", exclude_ids=["W004"])

    def test_unknown_template_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown template_id"):
            solve(self.household, "not-a-template")

    def test_invalid_households_are_rejected(self):
        for household in (None, {}, {"adults": True, "children": 0, "days": 3},
                          {"adults": 1, "children": -1, "days": 3},
                          {"adults": 1, "children": 0, "days": 0},
                          {"adults": 0, "children": 0, "days": 3},
                          {"adults": 1.5, "children": 0, "days": 3}):
            with self.subTest(household=household), self.assertRaises(ValueError):
                solve(household)

    def test_food_packs_and_required_water_volume(self):
        household = {"adults": 1, "children": 0, "days": 3}
        plan = solve(household, "standard")
        master = {item["id"]: item for item in model._read("data/items-master.json")["items"]}
        for entry in plan["items"]:
            item = master[entry["id"]]
            if item["meal_role"] != "drink":
                self.assertEqual(entry["count"] % item["pack_size"], 0)
        config = model._read("tests/sanity_config.json")
        self.assertEqual(plan["meta"]["water_ml"], config["water"]["ml_per_person_per_day"] * household["days"])

    def test_children_specials_are_not_added_for_adults_only(self):
        plan = solve({"adults": 2, "children": 0, "days": 3}, "baby")
        self.assertNotIn("P001", {item["id"] for item in plan["items"]})
        self.assertNotIn("P003", {item["id"] for item in plan["items"]})

    def test_infants_leave_food_unchanged_in_every_template(self):
        master = {item["id"]: item for item in model._read("data/items-master.json")["items"]}
        for template in model._read("templates/index.json"):
            plans = [solve({**self.household, "infants": infants}, template["id"]) for infants in (0, 1)]
            ordinary = [{item["id"]: item["count"] for item in plan["items"]
                         if master[item["id"]]["daily_coeff"] is None
                         and master[item["id"]]["meal_role"] != "drink"} for plan in plans]
            with self.subTest(template=template["id"]):
                self.assertEqual(*ordinary)
                self.assertEqual(plans[0]["meta"]["target_protein_g"], plans[1]["meta"]["target_protein_g"])

    def test_water_uses_both_child_and_infant_factors(self):
        household = {**self.household, "infants": 1}
        config = model._read("tests/sanity_config.json")["water"]
        water = next(item for item in model._read("data/items-master.json")["items"] if item["id"] == "W004")
        needed = config["ml_per_person_per_day"] * (household["adults"]
                 + config["child_factor"] * household["children"]
                 + config["infant_factor"] * household["infants"]) * household["days"]
        plan = solve(household, "standard")
        self.assertEqual(plan["meta"]["water_ml"], math.ceil(needed / water["water_per_unit"]) * water["water_per_unit"])
        self.assertEqual(model._water({"W004": (water, 1)}, math.nextafter(9000, math.inf))[1], 9)

    def test_special_food_basis_includes_infants_only_when_requested(self):
        original_read = model._read
        household = {"adults": 2, "children": 3, "infants": 1, "days": 3}
        for basis, people in (("all", 6), ("adults", 2), ("children", 3), ("infants", 1)):
            master = copy.deepcopy(original_read("data/items-master.json"))
            item = next(item for item in master["items"] if item["id"] == "P001")
            item["coeff_basis"] = basis
            with self.subTest(basis=basis), patch.object(model, "_read", side_effect=lambda path:
                              master if path == "data/items-master.json" else original_read(path)):
                plan = solve(household, "baby")
                counts = {entry["id"]: entry["count"] for entry in plan["items"]}
                expected = math.ceil(item["daily_coeff"] * people * household["days"] / item["pack_size"]) * item["pack_size"]
                self.assertEqual(counts["P001"], expected)

    def test_meal_priority_precedes_extreme_template_preference(self):
        original_read = model._read
        template = copy.deepcopy(original_read("templates/standard.json"))
        next(item for item in template["items"] if item["ref"] == "S006")["weight"] *= 1000
        with patch.object(model, "_read", side_effect=lambda path:
                          template if path == "templates/standard.json" else original_read(path)):
            plan = solve(self.household, "standard")
        self.assertEqual(plan["meta"]["meal_extras"], {})
        self.assert_meal_extras_match_counts(plan, self.household)

    def assert_meal_extras_match_counts(self, plan, household):
        config = model._read("tests/sanity_config.json")["meals"]
        master = {item["id"]: item for item in model._read("data/items-master.json")["items"]}
        meals = config["per_person_per_day"] * (household["adults"] + household["children"]) * household["days"]
        for role, per_meal in config["max_servings_per_meal_by_role"].items():
            entries = [entry for entry in plan["items"] if master[entry["id"]]["meal_role"] == role]
            got = sum(entry["count"] / master[entry["id"]]["units_per_serving"] for entry in entries)
            rounding = sum((master[entry["id"]]["pack_size"] - 1) / master[entry["id"]]["units_per_serving"] for entry in entries)
            expected = max(0, got - meals * per_meal - rounding)
            extra = plan["meta"]["meal_extras"].get(role)
            if expected > model.TOLERANCE:
                self.assertAlmostEqual(extra["servings"], expected)
                self.assertTrue(extra["reason"].strip())
            else:
                self.assertIsNone(extra)

    def test_necessary_extra_meals_are_explained(self):
        for household, template in (({"adults": 10, "children": 0, "days": 7}, "standard"),
                                    ({"adults": 4, "children": 0, "days": 7}, "family-kids")):
            with self.subTest(template=template):
                plan = solve(household, template)
                self.assertTrue(plan["meta"]["meal_extras"])
                self.assert_meal_extras_match_counts(plan, household)

    def test_rationale_covers_water_specials_and_food(self):
        plan = solve({**self.household, "infants": 1}, "baby")
        rationale = plan["meta"]["rationale"]
        self.assertEqual(set(rationale), {item["id"] for item in plan["items"]})
        self.assertIn("乳幼児1人", rationale["P001"])
        factor = model._read("tests/sanity_config.json")["water"]["infant_factor"]
        self.assertIn(f"乳幼児{factor:g}×1", rationale["W004"])
        self.assertIn("購入単位", rationale["S002"])
        for text in rationale.values():
            self.assertIn("×", text)

    def test_weights_change_the_preferred_mix(self):
        original_read = model._read
        template = copy.deepcopy(original_read("templates/standard.json"))
        first = solve(self.household, "standard")
        for entry in template["items"]:
            if entry["ref"] == "S006":
                entry["weight"] = sum(item["weight"] for item in template["items"])
        with patch.object(model, "_read", side_effect=lambda path:
                          template if path == "templates/standard.json" else original_read(path)):
            second = solve(self.household, "standard")
        counts_before = {item["id"]: item["count"] for item in first["items"]}
        counts_after = {item["id"]: item["count"] for item in second["items"]}
        self.assertGreater(counts_after["S006"], counts_before["S006"])


if __name__ == "__main__":
    unittest.main()
