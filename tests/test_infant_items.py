"""乳幼児がいる世帯には、テンプレートにかかわらず、乳児用の品目を出す（Issue #24）。

オーナー決定 2026-11-05（docs/decisions.md）。乳幼児は普通の食事には数えず、ミルクなどの特別食だけで数える。
"""
import unittest

from harness_common import load_template_index, solver_available

MILK_IDS = {"P001", "P002"}          # 乳児用液体ミルク、乳児用粉ミルク
BABY_FOOD_IDS = {"P003"}             # ベビーフード
INFANT_IDS = MILK_IDS | BABY_FOOD_IDS


@unittest.skipUnless(solver_available(), "solver が未作成")
class TestInfantItems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solver import solve
        cls.solve = staticmethod(solve)

    def _counts(self, household, template_id):
        return {i["id"]: i["count"] for i in self.solve(household, template_id)["items"]}

    def test_milk_is_included_in_every_template_when_infants_present(self):
        for template in load_template_index():
            for infants in (1, 2):
                for days in (3, 7):
                    household = {"adults": 2, "children": 1, "infants": infants, "days": days}
                    with self.subTest(template=template["id"], infants=infants, days=days):
                        counts = self._counts(household, template["id"])
                        self.assertGreater(sum(counts.get(i, 0) for i in MILK_IDS), 0,
                                           "乳幼児がいるのに、ミルクがない")

    def test_milk_grows_with_infants(self):
        for template in load_template_index():
            with self.subTest(template=template["id"]):
                one = self._counts({"adults": 2, "children": 0, "infants": 1, "days": 7}, template["id"])
                two = self._counts({"adults": 2, "children": 0, "infants": 2, "days": 7}, template["id"])
                self.assertGreater(sum(two.get(i, 0) for i in MILK_IDS),
                                   sum(one.get(i, 0) for i in MILK_IDS))

    def test_no_infant_items_without_infants(self):
        for template in load_template_index():
            with self.subTest(template=template["id"]):
                counts = self._counts({"adults": 2, "children": 1, "infants": 0, "days": 3}, template["id"])
                self.assertFalse(INFANT_IDS & set(counts), "乳幼児がいないのに、乳児用の品目がある")

    def test_excluded_milk_is_respected(self):
        # 除外の指定は、乳児用の品目にも効く（液体ミルクを除けば、粉ミルクで出す）
        result = self.solve({"adults": 2, "children": 0, "infants": 1, "days": 3}, "standard", exclude_ids=["P001"])
        ids = {i["id"] for i in result["items"]}
        self.assertNotIn("P001", ids)
        self.assertIn("P002", ids)

    def test_infant_items_have_rationale(self):
        result = self.solve({"adults": 2, "children": 0, "infants": 1, "days": 3}, "standard")
        for item in result["items"]:
            if item["id"] in INFANT_IDS:
                self.assertTrue(result["meta"]["rationale"].get(item["id"]), item["id"])


if __name__ == "__main__":
    unittest.main()
