"""ソルバーの常識チェック。solver パッケージができるまではスキップされる。

インターフェイスは CLAUDE.md の「ソルバー」の節を参照。判定の閾値は tests/sanity_config.json にある。
"""
import unittest

from harness_common import check_plan, iter_cases, load_config, load_master, solver_available

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

    def test_deterministic(self):
        household = {"adults": 2, "children": 1, "days": 3}
        first = self.solve(household=household, template_id="standard", exclude_tags=[], exclude_ids=[])
        second = self.solve(household=household, template_id="standard", exclude_tags=[], exclude_ids=[])
        self.assertEqual(first["items"], second["items"], "同じ入力で結果が変わった")


if __name__ == "__main__":
    unittest.main()
