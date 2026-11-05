"""東京備蓄ナビの計算の再現（comparison/tokyo_navi.py）のテスト。モジュールができるまではスキップされる。

期待値は docs/tokyo_bichiku_navi.md の 3.5（2026-10-22 に公開サイトをブラウザで操作して記録した結果）。
再現が公開サイトの動作と一致していることを確かめる。
"""
import importlib.util
import unittest

from harness_common import ROOT  # noqa: F401（sys.path にリポジトリ直下を入れるため）

AVAILABLE = importlib.util.find_spec("comparison") is not None and \
    importlib.util.find_spec("comparison.tokyo_navi") is not None

# (大人, 子供 3歳〜小6, 乳幼児, 日数) → {東京の品目 id: 数量}。id は stockpile.config.js のもの。
# 1 水(L) / 2 レトルトご飯(食) / 3 レトルト食品(個) / 11 無洗米(kg) / 7 チーズ・プロテインバー等 /
# 10 乾麺 即席麺 / 45 粉ミルク / 46 液体ミルク。表にない品目（—）は結果に含まれない（0）。
OBSERVED = [
    ((1, 0, 0, 3), {"1": 9, "2": 9, "3": 3, "11": 2, "7": 1, "10": 3}),
    ((1, 0, 0, 7), {"1": 21, "2": 21, "3": 7, "11": 3, "7": 2, "10": 7}),
    ((2, 0, 0, 3), {"1": 18, "2": 18, "3": 6, "11": 3, "7": 2, "10": 3}),
    ((2, 0, 0, 7), {"1": 42, "2": 42, "3": 14, "11": 6, "7": 4, "10": 7}),
    ((2, 1, 0, 3), {"1": 26, "2": 26, "3": 9, "11": 4, "7": 3, "10": 3}),
    ((2, 1, 0, 7), {"1": 59, "2": 59, "3": 20, "11": 8, "7": 6, "10": 7}),
    ((2, 0, 1, 3), {"1": 26, "2": 18, "3": 6, "11": 3, "7": 2, "10": 3, "45": 18, "46": 18}),
    ((0, 0, 1, 3), {"1": 8, "2": 0, "3": 0, "11": 0, "7": 0, "10": 0, "45": 18, "46": 18}),
    ((5, 0, 0, 3), {"1": 45, "2": 45, "3": 15, "11": 6, "7": 5, "10": 3}),
    ((6, 0, 0, 3), {"1": 54, "2": 54, "3": 18, "11": 7, "7": 6, "10": 6}),
    ((6, 0, 0, 7), {"1": 126, "2": 126, "3": 42, "11": 16, "7": 12, "10": 14}),
]


@unittest.skipUnless(AVAILABLE, "comparison/tokyo_navi.py が未作成")
class TokyoNaviTest(unittest.TestCase):
    def setUp(self):
        from comparison.tokyo_navi import tokyo_plan
        self.tokyo_plan = tokyo_plan

    def test_reproduces_the_observed_results(self):
        for (adults, children, infants, days), expected in OBSERVED:
            household = {"adults": adults, "children": children, "infants": infants, "days": days}
            result = self.tokyo_plan(household)
            for tokyo_id, quantity in expected.items():
                with self.subTest(**household, item=tokyo_id):
                    self.assertEqual(result.get(tokyo_id, 0), quantity)

    def test_only_3_or_7_days(self):
        """東京備蓄ナビの日数は、住まいの種類で決まる 3日（戸建て）か 7日（集合住宅）だけ。外挿しない。"""
        for days in (1, 5, 14):
            with self.subTest(days=days):
                with self.assertRaises(ValueError):
                    self.tokyo_plan({"adults": 2, "children": 0, "infants": 0, "days": days})

    def test_zero_items_are_omitted(self):
        result = self.tokyo_plan({"adults": 2, "children": 0, "infants": 0, "days": 3})
        self.assertNotIn("45", result, "乳幼児がいない世帯に粉ミルクが出ている")
        self.assertTrue(all(q > 0 for q in result.values()))


if __name__ == "__main__":
    unittest.main()
