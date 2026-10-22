"""ソルバーの常識チェック。solver パッケージができるまではスキップされる。

インターフェイスは CLAUDE.md の「ソルバー」の節を参照。判定の閾値は tests/sanity_config.json にある。
"""
import math
import unittest

from harness_common import (
    check_plan, iter_cases, load_config, load_master, load_template, solver_available,
)

SKIP_REASON = "solver パッケージが未実装（CLAUDE.md の「1. ソルバー」を参照）"


def assert_plan_passes(test, plan, household, template_id, master, config, **excludes):
    for name, ok, detail in check_plan(plan, household, template_id, master, config, **excludes):
        if ok is None:  # データ未整備で判定できないチェック
            continue
        test.assertTrue(ok, f"{name}: {detail}")


@unittest.skipUnless(solver_available(), SKIP_REASON)
class SolverSanityTest(unittest.TestCase):
    def setUp(self):
        from solver import solve
        self.solve = solve
        self.master = load_master()
        self.config = load_config()

    def test_all_cases_pass_sanity_checks(self):
        for case in iter_cases(self.config):
            with self.subTest(**case["household"], template=case["template_id"]):
                plan = self.solve(household=case["household"], template_id=case["template_id"],
                                  exclude_tags=[], exclude_ids=[])
                assert_plan_passes(self, plan, case["household"], case["template_id"],
                                   self.master, self.config)

    def test_extreme_households(self):
        """世帯の規模が極端でも、常識的な結果になる（絶対数の上限に頼っていないことの確認）。"""
        for household in ({"adults": 1, "children": 0, "days": 3},
                          {"adults": 10, "children": 0, "days": 7},
                          {"adults": 2, "children": 6, "days": 7}):
            with self.subTest(**household):
                plan = self.solve(household=household, template_id="standard",
                                  exclude_tags=[], exclude_ids=[])
                assert_plan_passes(self, plan, household, "standard", self.master, self.config)

    def test_vegetable_juice_is_not_overloaded(self):
        """回帰テスト：栄養の乏しい野菜ジュース（V001）を大量に積まない。"""
        caps = self.config["per_item_caps"]["max_units_per_person_day_by_role"]
        juice = self.master["V001"]
        for case in iter_cases(self.config):
            household = case["household"]
            people = household["adults"] + household["children"]
            plan = self.solve(household=household, template_id=case["template_id"],
                              exclude_tags=[], exclude_ids=[])
            count = sum(e["count"] for e in plan["items"] if e["id"] == "V001")
            limit = caps[juice["meal_role"]] * people * household["days"] + juice["pack_size"]
            with self.subTest(**household, template=case["template_id"]):
                self.assertLessEqual(count, limit)

    def test_exclusions_are_respected(self):
        household = {"adults": 2, "children": 1, "days": 3}
        plan = self.solve(household=household, template_id=None,
                          exclude_tags=["needs-cook", "needs-heat"], exclude_ids=["V001"])
        assert_plan_passes(self, plan, household, None, self.master, self.config,
                           exclude_tags=["needs-cook", "needs-heat"], exclude_ids=["V001"])

    def test_infant_items_follow_the_number_of_infants(self):
        """回帰テスト：子供（3歳以上）を乳児として数え、液体ミルク63本を出していた。
        乳児用の特別食（coeff_basis が infants）は、乳幼児の人数だけで決まる。"""
        infant_ids = [r["ref"] for r in load_template("baby")["items"]
                      if self.master[r["ref"]].get("coeff_basis") == "infants"]
        self.assertTrue(infant_ids, "baby テンプレートに乳児用の特別食がない")

        no_infant = {"adults": 2, "children": 3, "infants": 0, "days": 7}
        plan = self.solve(household=no_infant, template_id="baby", exclude_tags=[], exclude_ids=[])
        counts = {e["id"]: e["count"] for e in plan["items"]}
        for item_id in infant_ids:
            with self.subTest(household="乳幼児なし", item=item_id):
                self.assertEqual(counts.get(item_id, 0), 0)

        one_infant = {"adults": 2, "children": 0, "infants": 1, "days": 3}
        plan = self.solve(household=one_infant, template_id="baby", exclude_tags=[], exclude_ids=[])
        counts = {e["id"]: e["count"] for e in plan["items"]}
        for item_id in infant_ids:
            item = self.master[item_id]
            expected = math.ceil(item["daily_coeff"] * 1 * 3 / item["pack_size"]) * item["pack_size"]
            with self.subTest(household="乳幼児1人", item=item_id):
                self.assertEqual(counts.get(item_id, 0), expected)
        assert_plan_passes(self, plan, one_infant, "baby", self.master, self.config)

    def test_infants_do_not_change_ordinary_food(self):
        """乳幼児は普通の食事に数えない。変わるのは水と乳児用の特別食だけ。"""
        def ordinary(household):
            plan = self.solve(household=household, template_id="standard", exclude_tags=[], exclude_ids=[])
            return {e["id"]: e["count"] for e in plan["items"]
                    if self.master[e["id"]]["daily_coeff"] is None
                    and self.master[e["id"]]["meal_role"] != "drink"}
        self.assertEqual(ordinary({"adults": 2, "children": 1, "days": 3}),
                         ordinary({"adults": 2, "children": 1, "infants": 1, "days": 3}))

    def test_infants_key_is_optional_and_validated(self):
        base = {"adults": 2, "children": 1, "days": 3}
        without = self.solve(household=base, template_id="standard", exclude_tags=[], exclude_ids=[])
        with_zero = self.solve(household={**base, "infants": 0}, template_id="standard",
                               exclude_tags=[], exclude_ids=[])
        self.assertEqual(without["items"], with_zero["items"], "infants を省略したときは 0 と同じ")
        for bad in (-1, 1.5, True, "1"):
            with self.subTest(infants=bad):
                with self.assertRaises(ValueError):
                    self.solve(household={**base, "infants": bad}, template_id="standard",
                               exclude_tags=[], exclude_ids=[])

    def test_standard_template_fits_the_number_of_meals(self):
        """標準テンプレート（実験で主に使う）は、食事の回数を超える主食・主菜を足さずに済む。"""
        for case in iter_cases(self.config):
            if case["template_id"] != "standard":
                continue
            plan = self.solve(household=case["household"], template_id="standard",
                              exclude_tags=[], exclude_ids=[])
            with self.subTest(**case["household"]):
                self.assertFalse(plan["meta"].get("meal_extras"),
                                 f"食事の回数を超えて追加した: {plan['meta'].get('meal_extras')}")

    def test_deterministic(self):
        household = {"adults": 2, "children": 1, "days": 3}
        first = self.solve(household=household, template_id="standard", exclude_tags=[], exclude_ids=[])
        second = self.solve(household=household, template_id="standard", exclude_tags=[], exclude_ids=[])
        self.assertEqual(first["items"], second["items"], "同じ入力で結果が変わった")
        self.assertEqual(first["meta"].get("rationale"), second["meta"].get("rationale"),
                         "同じ入力で根拠の説明が変わった")


if __name__ == "__main__":
    unittest.main()
