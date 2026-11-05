"""12か月の消費の割り振り（rotation）と、カレンダー用のデータ（Issue #22）。

守ること：
- 12か月で、すべての品目を、ソルバーの数量どおりに使い切る
- どの月にも食べるものがある（「忘れる」を防ぐため、空の月を作らない）
- 月ごとの個数の合計の差は、最大の月と最小の月で1個以内
- 同じ入力からは同じ結果
"""
import importlib.util
import re
import unittest

from harness_common import ROOT, load_master, load_template_index

AVAILABLE = importlib.util.find_spec("rotation") is not None
MONTHS = 12

# 小さい世帯と大きい世帯を、すべてのテンプレートで確かめる
# （総量が12未満の品目ばかりになる小さい世帯で、空の月ができやすい）
HOUSEHOLDS = [
    {"adults": 1, "children": 0, "infants": 0, "days": 3},
    {"adults": 2, "children": 1, "infants": 1, "days": 3},
    {"adults": 4, "children": 3, "infants": 1, "days": 7},
]


def _cases():
    for template in load_template_index():
        for household in HOUSEHOLDS:
            yield household, template["id"]


@unittest.skipUnless(AVAILABLE, "rotation/ が未作成")
class TestAllocate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solver import solve
        from rotation import allocate

        cls.allocate = staticmethod(allocate)
        cls.results = [(h, t, solve(h, t)) for h, t in _cases()]

    def test_twelve_months(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                self.assertEqual(len(self.allocate(result)), MONTHS)

    def test_counts_are_positive_integers(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for month in self.allocate(result):
                    for entry in month:
                        self.assertIsInstance(entry["count"], int)
                        self.assertGreater(entry["count"], 0)

    def test_every_item_is_used_up_in_twelve_months(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                expected = {item["id"]: item["count"] for item in result["items"]}
                used = {}
                for month in self.allocate(result):
                    ids = [entry["id"] for entry in month]
                    self.assertEqual(len(ids), len(set(ids)), "同じ月に同じ品目が2回出ている")
                    for entry in month:
                        used[entry["id"]] = used.get(entry["id"], 0) + entry["count"]
                self.assertEqual(used, expected)

    def test_every_month_has_something_to_eat(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for k, month in enumerate(self.allocate(result)):
                    self.assertTrue(month, f"{k + 1}か月目に食べるものがない")

    def test_monthly_totals_differ_by_at_most_one(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                totals = [sum(e["count"] for e in month) for month in self.allocate(result)]
                self.assertLessEqual(max(totals) - min(totals), 1, totals)

    def test_same_input_same_output(self):
        household, template_id, result = self.results[0]
        self.assertEqual(self.allocate(result), self.allocate(result))


@unittest.skipUnless(AVAILABLE, "rotation/ が未作成")
class TestBuildPlan(unittest.TestCase):
    def test_plan_matches_solver_and_master(self):
        from solver import solve
        from rotation import allocate, build_plan

        master = load_master()
        household = {"adults": 2, "children": 1, "infants": 1, "days": 3}
        for template_id in ("standard", "baby"):
            with self.subTest(template=template_id):
                plan = build_plan(household, template_id)
                result = solve(household, template_id)
                self.assertEqual(plan["template_id"], template_id)
                self.assertEqual(plan["household"]["adults"], household["adults"])
                self.assertEqual(plan["household"]["children"], household["children"])
                self.assertEqual(plan["household"]["infants"], household["infants"])
                self.assertEqual(plan["household"]["days"], household["days"])
                self.assertEqual(
                    [(i["id"], i["count"]) for i in plan["items"]],
                    [(i["id"], i["count"]) for i in result["items"]],
                )
                for item in plan["items"]:
                    self.assertEqual(item["name"], master[item["id"]]["name"])
                    self.assertEqual(item["unit"], master[item["id"]]["consume_unit"])
                self.assertEqual(plan["months"], allocate(result))

    def test_plan_passes_exclusions_to_solver(self):
        from solver import solve
        from rotation import build_plan

        household = {"adults": 2, "children": 0, "days": 3}
        plan = build_plan(household, "standard", exclude_tags=["needs-cook"], exclude_ids=["V001"])
        result = solve(household, "standard", exclude_tags=["needs-cook"], exclude_ids=["V001"])
        self.assertEqual(
            [(i["id"], i["count"]) for i in plan["items"]],
            [(i["id"], i["count"]) for i in result["items"]],
        )


class TestCalendarChildFactor(unittest.TestCase):
    def test_calendar_does_not_use_child_factor_06(self):
        # 子供の係数は 0.8 にそろえる（オーナー承認 2026-10-22）
        html = (ROOT / "calender.html").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"children\s*\)?\s*\*\s*0\.6\b", html))


if __name__ == "__main__":
    unittest.main()
