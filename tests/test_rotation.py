"""12か月の消費の割り振り（rotation）と、カレンダー用のデータ（Issue #22）。

守ること：
- 12か月で、すべての品目を、ソルバーの数量どおりに使い切る
- どの月にも食べるものがある（「忘れる」を防ぐため、空の月を作らない）
- 月ごとの個数の合計の差は、最大の月と最小の月で1個以内
- 同じ入力からは同じ結果

強めた約束（Issue #26、オーナー承認 2026-11-12）：
- 毎月、主食か主菜を1個以上、水以外の食べ物を2個以上
- 乳児用の品目（coeff_basis が infants）は12か月の割り振りに入れない（普段の授乳で使った分を買い足す）
- 1日に食べる食べ物（水以外）は「一人一品・二品まで」＝ 食べる人数（大人＋子供）× 2 以下。
  収まらない月は、消費日を増やす（必要な日数より多くはしない）
"""
import importlib.util
import re
import unittest

from harness_common import ROOT, load_master, load_template_index

MASTER = load_master()
MEAL_ROLES_SM = ("staple", "main")
PORTIONS_PER_PERSON_DAY = 2   # 一人一品・二品まで（オーナー決定 2026-11-12）


def is_infant_item(item_id):
    return MASTER[item_id].get("coeff_basis") == "infants"


def is_food(item_id):
    return MASTER[item_id]["meal_role"] != "drink"

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
                expected = {item["id"]: item["count"] for item in result["items"]
                            if not is_infant_item(item["id"])}
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

    def test_infant_items_are_not_in_the_monthly_rotation(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for month in self.allocate(result):
                    for entry in month:
                        self.assertFalse(is_infant_item(entry["id"]), entry["id"])

    def test_every_month_has_staple_or_main(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for k, month in enumerate(self.allocate(result)):
                    self.assertTrue(any(MASTER[e["id"]]["meal_role"] in MEAL_ROLES_SM for e in month),
                                    f"{k + 1}か月目に主食も主菜もない")

    def test_every_month_has_at_least_two_foods(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for k, month in enumerate(self.allocate(result)):
                    foods = sum(e["count"] for e in month if is_food(e["id"]))
                    self.assertGreaterEqual(foods, 2, f"{k + 1}か月目の水以外の食べ物が {foods} 個")

    def test_same_input_same_output(self):
        household, template_id, result = self.results[0]
        self.assertEqual(self.allocate(result), self.allocate(result))


@unittest.skipUnless(AVAILABLE, "rotation/ が未作成")
class TestConsumptionDays(unittest.TestCase):
    """消費日ごとの割り振り。rotation.schedule(result, household) は、長さ12の月のリストで、
    各月は消費日のリスト、各消費日は [{"id", "count"}] のリスト。"""

    @classmethod
    def setUpClass(cls):
        from solver import solve
        from rotation import allocate, schedule

        cls.allocate = staticmethod(allocate)
        cls.schedule = staticmethod(schedule)
        cls.results = [(h, t, solve(h, t)) for h, t in _cases()]

    @staticmethod
    def _limit(household):
        return PORTIONS_PER_PERSON_DAY * (household["adults"] + household["children"])

    def test_days_add_up_to_the_month(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                months = self.allocate(result)
                days = self.schedule(result, household)
                self.assertEqual(len(days), MONTHS)
                for month, month_days in zip(months, days):
                    self.assertGreaterEqual(len(month_days), 1)
                    total = {}
                    for day in month_days:
                        for e in day:
                            self.assertIsInstance(e["count"], int)
                            self.assertGreater(e["count"], 0)
                            total[e["id"]] = total.get(e["id"], 0) + e["count"]
                    self.assertEqual(total, {e["id"]: e["count"] for e in month})

    def test_each_day_is_one_or_two_portions_per_person(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for k, month_days in enumerate(self.schedule(result, household)):
                    for d, day in enumerate(month_days):
                        foods = sum(e["count"] for e in day if is_food(e["id"]))
                        self.assertLessEqual(foods, self._limit(household),
                                             f"{k + 1}か月目の{d + 1}日目に {foods} 個")
                        self.assertGreaterEqual(foods, 1, f"{k + 1}か月目の{d + 1}日目に食べ物がない")

    def test_no_more_days_than_needed(self):
        for household, template_id, result in self.results:
            with self.subTest(household=household, template=template_id):
                for k, (month, month_days) in enumerate(zip(self.allocate(result),
                                                            self.schedule(result, household))):
                    foods = sum(e["count"] for e in month if is_food(e["id"]))
                    needed = max(1, -(-foods // self._limit(household)))
                    self.assertEqual(len(month_days), needed, f"{k + 1}か月目")

    def test_small_household_eats_on_one_day(self):
        household = {"adults": 1, "children": 0, "infants": 0, "days": 3}
        result = next(r for h, t, r in self.results if h == household and t == "standard")
        self.assertTrue(all(len(m) == 1 for m in self.schedule(result, household)))

    def test_same_input_same_output(self):
        household, template_id, result = self.results[-1]
        self.assertEqual(self.schedule(result, household), self.schedule(result, household))


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
                from rotation import schedule
                self.assertEqual(plan["days"], schedule(result, household))

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
