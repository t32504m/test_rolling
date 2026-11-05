"""東京備蓄ナビ（https://www.bichiku.metro.tokyo.lg.jp/）の備蓄量の計算を再現する。

計算方法は docs/tokyo_bichiku_navi.md の記録だけを根拠にする。設定値は data/tokyo_bichiku_navi.json から読む。
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "tokyo_bichiku_navi.json"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _members(household, config):
    """世帯を、東京の年代区分の1人ずつの並びに展開する。"""
    members = []
    for key, group in config["age_groups"].items():
        if key.startswith("_"):
            continue
        members += [group] * int(household.get(key, 0) or 0)
    return members


def tokyo_plan(household):
    """世帯 → {東京の品目 id: 数量}。食品と水だけを返し、数量 0 の品目は返さない。

    household はソルバーと同じ形 {"adults", "children", "infants"（省略可）, "days"}。
    days は 3（戸建て）か 7（集合住宅）だけ。ほかの値は東京備蓄ナビで表せないので ValueError。
    「適宜」「適量」の品目（D2）は数量がないので返さない。品目の有無は tokyo_unquantified_items() で得る。
    """
    config = load_config()
    dwelling = {v: k for k, v in config["days_by_dwelling"].items() if not k.startswith("_")}
    days = household.get("days")
    if days not in dwelling:
        raise ValueError(f"東京備蓄ナビの日数は 3（戸建て）か 7（集合住宅）だけです: days={days!r}")
    dwelling = dwelling[days]

    members = _members(household, config)
    infants_only = all(group == "infant" for group in members)

    fixed = config["fixed_quantity"]
    size = "small" if len(members) <= fixed["max_members_small"] else "large"

    plan = {}
    for item in config["items"]:
        calc = item["calc"]
        if calc == "D2":
            continue
        if calc == "A2":
            quantity = 0 if infants_only else fixed[dwelling][size]
        else:
            # 公開サイトの JavaScript と同じ順序：1人ずつの値を足してから係数を掛け、最後に1回だけ切り上げる
            total = 0
            for group in members:
                total += item["required"][group]
            if calc == "basic":
                quantity = math.ceil(total * days)
            elif calc == "A1":
                quantity = 0 if infants_only else total
                if dwelling == "apartment":
                    quantity *= config["a1_apartment_multiplier"]
            else:
                raise ValueError(f"未知の計算の区分: {calc}")
        if quantity > 0:
            plan[item["id"]] = quantity
    return plan


def tokyo_unquantified_items(household):
    """数量を出さず「適宜」「適量」と表示される品目（D2）の id の並び。乳幼児だけの世帯では出ない。"""
    config = load_config()
    if all(group == "infant" for group in _members(household, config)):
        return []
    return [item["id"] for item in config["items"] if item["calc"] == "D2"]
