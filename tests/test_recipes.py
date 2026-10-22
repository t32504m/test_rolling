"""備蓄品レシピ（data/recipes.json）の整合性テスト。ファイルができるまではスキップされる。

形式は Issue「備蓄品レシピの収集」を参照。
"""
import unittest

from harness_common import ROOT, load_json, load_master

RECIPES = ROOT / "data" / "recipes.json"


@unittest.skipUnless(RECIPES.is_file(), "data/recipes.json が未作成")
class RecipesTest(unittest.TestCase):
    def setUp(self):
        self.recipes = load_json("data/recipes.json")["recipes"]
        self.master = load_master()

    def test_ids_are_unique(self):
        ids = [r["id"] for r in self.recipes]
        self.assertEqual(len(ids), len(set(ids)), "レシピIDが重複している")

    def test_every_recipe_has_a_source_url(self):
        for recipe in self.recipes:
            with self.subTest(recipe=recipe.get("id")):
                source = recipe.get("source", {})
                url = source.get("url")
                self.assertTrue(isinstance(url, str) and url.startswith("http"), "source.url がない")
                self.assertTrue(source.get("publisher"), "source.publisher（公開元）がない")

    def test_uses_only_master_items(self):
        for recipe in self.recipes:
            with self.subTest(recipe=recipe["id"]):
                uses = recipe.get("uses", [])
                self.assertTrue(uses, "備蓄品を1つも使っていない")
                for use in uses:
                    self.assertIn(use["item_id"], self.master, f"マスタにない品目 {use['item_id']}")
                    self.assertGreater(use["amount"], 0)


if __name__ == "__main__":
    unittest.main()
