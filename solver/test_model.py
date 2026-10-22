"""Additional solver tests; synthetic nutrients never modify the food master.

Run with: python3 -m unittest solver.test_model -v
"""

import copy
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

    def test_partial_protein_data_is_explicitly_unassessed(self):
        original_read = model._read
        master = copy.deepcopy(original_read("data/items-master.json"))
        for item in master["items"]:
            item["protein_per_unit"] = 0
        next(item for item in master["items"] if item["id"] == "S002")["protein_per_unit"] = None
        with patch.object(model, "_read", side_effect=lambda path:
                          master if path == "data/items-master.json" else original_read(path)):
            meta = solve(self.household, "standard")["meta"]
        self.assertEqual(meta["protein_constraint"], "missing_data")
        self.assertEqual(meta["missing_protein_ids"], ["S002"])
        self.assertIsNone(meta["total_protein_g"])

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
