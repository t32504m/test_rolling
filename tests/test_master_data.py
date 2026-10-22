"""品目マスタ・テンプレート・閾値設定の整合性テスト（今すぐ実行される）。"""
import numbers
import unittest

from harness_common import load_config, load_json, load_template, load_template_index, ROOT

REQUIRED_KEYS = (
    "id", "name", "category", "meal_role", "tags", "consume_unit", "daily_coeff",
    "unit_gram", "cal_per_unit", "water_per_unit", "pack_size", "source",
)
ALLOWED_ROLES = {"drink", "staple", "main", "side", "snack", "special"}
# 特別食（daily_coeff のある品目）の数量の基準になる人。infants は乳幼児
ALLOWED_COEFF_BASIS = {"all", "adults", "children", "infants"}
# 乳児用の特別食。東京備蓄ナビと同じく、乳幼児の人数だけで数える（docs/tokyo_bichiku_navi.md）
INFANT_ONLY_IDS = ("P001", "P002", "P003")
# 将来追加される栄養値。入れる場合は数値で、出典（source）を伴うこと
OPTIONAL_NUTRIENTS = ("protein_per_unit", "salt_g_per_unit")


class MasterDataTest(unittest.TestCase):
    def setUp(self):
        self.items = load_json("data/items-master.json")["items"]

    def test_ids_are_unique(self):
        ids = [i["id"] for i in self.items]
        self.assertEqual(len(ids), len(set(ids)), "品目IDが重複している")

    def test_required_keys(self):
        for item in self.items:
            with self.subTest(item=item.get("id")):
                missing = [k for k in REQUIRED_KEYS if k not in item]
                self.assertFalse(missing, f"必須の項目がない: {missing}")

    def test_meal_role_is_known(self):
        for item in self.items:
            with self.subTest(item=item["id"]):
                self.assertIn(item["meal_role"], ALLOWED_ROLES)

    def test_numbers_are_valid(self):
        for item in self.items:
            with self.subTest(item=item["id"]):
                for key in ("cal_per_unit", "water_per_unit", "unit_gram"):
                    value = item[key]
                    self.assertIsInstance(value, numbers.Real, f"{key} が数値でない")
                    self.assertGreaterEqual(value, 0, f"{key} が負")
                self.assertIsInstance(item["pack_size"], int)
                self.assertGreaterEqual(item["pack_size"], 1)
                for key in OPTIONAL_NUTRIENTS:
                    if key in item:
                        self.assertIsInstance(item[key], numbers.Real, f"{key} が数値でない")
                        self.assertGreaterEqual(item[key], 0, f"{key} が負")

    def test_every_item_has_a_source(self):
        """数値の根拠がない品目を許さない（出典なしの数値変更を防ぐ）。"""
        for item in self.items:
            with self.subTest(item=item["id"]):
                source = item["source"]
                self.assertIsInstance(source, dict)
                basis = source.get("nutrition_basis")
                self.assertTrue(isinstance(basis, str) and basis.strip(),
                                "source.nutrition_basis（栄養値の根拠）が空")

    def test_nutrients_have_their_own_source(self):
        """たんぱく質などの栄養値を追加するときは、その値の根拠（URL）も必須。"""
        for item in self.items:
            with self.subTest(item=item["id"]):
                if "protein_per_unit" in item:
                    url = item["source"].get("protein_url")
                    self.assertTrue(isinstance(url, str) and url.startswith("http"),
                                    "protein_per_unit の根拠 source.protein_url がない")

    def test_special_items_have_a_known_basis(self):
        for item in self.items:
            if item["daily_coeff"] is not None:
                with self.subTest(item=item["id"]):
                    self.assertIn(item.get("coeff_basis") or "all", ALLOWED_COEFF_BASIS)

    def test_infant_items_count_only_infants(self):
        items = {i["id"]: i for i in self.items}
        for item_id in INFANT_ONLY_IDS:
            with self.subTest(item=item_id):
                self.assertEqual(items[item_id].get("coeff_basis"), "infants")

    def test_drink_items_provide_water(self):
        for item in self.items:
            if item["meal_role"] == "drink":
                with self.subTest(item=item["id"]):
                    self.assertGreater(item["water_per_unit"], 0)


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.ids = {i["id"] for i in load_json("data/items-master.json")["items"]}

    def test_index_files_exist(self):
        for entry in load_template_index():
            with self.subTest(template=entry["id"]):
                self.assertTrue((ROOT / "templates" / entry["file"]).is_file())

    def test_refs_and_weights(self):
        for entry in load_template_index():
            template = load_template(entry["id"])
            with self.subTest(template=entry["id"]):
                self.assertEqual(template["id"], entry["id"])
                for ref in template["items"]:
                    self.assertIn(ref["ref"], self.ids, f"マスタにない品目 {ref['ref']}")
                    self.assertGreater(ref["weight"], 0)
                self.assertIsInstance(template.get("exclude_tags", []), list)


class SanityConfigTest(unittest.TestCase):
    def test_thresholds_are_positive(self):
        config = load_config()
        self.assertGreater(config["energy"]["adult_kcal_per_day"], 0)
        self.assertGreaterEqual(config["energy"]["max_ratio_to_target"], 1)
        self.assertGreater(config["water"]["ml_per_person_per_day"], 0)
        self.assertTrue(0 < config["water"]["child_factor"] <= 1)
        self.assertTrue(0 < config["water"]["infant_factor"] <= 1)
        self.assertGreater(config["meals"]["per_person_per_day"], 0)
        for value in config["meals"]["max_servings_per_meal_by_role"].values():
            self.assertGreater(value, 0)
        caps = config["per_item_caps"]
        self.assertTrue(0 < caps["max_kcal_share_of_total"] <= 1)
        for value in caps["max_units_per_person_day_by_role"].values():
            self.assertGreater(value, 0)


if __name__ == "__main__":
    unittest.main()
