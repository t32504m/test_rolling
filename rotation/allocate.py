"""12か月の消費の割り振り。

考え方：
1. 品目ごとに、その品目の1個1個を、1年の中で等間隔の位置に置く
   （count 個なら、位置は (j + 0.5) / count。j = 0 .. count-1）。
2. すべての品目の1個1個を、位置の順に一列に並べる（同じ位置なら品目 ID の順）。
3. 一列を12の区間に切る。k か月目は、全体の個数 N のうち
   floor(k*N/12) 番目から floor((k+1)*N/12) 番目の手前まで。

こうすると、
- 各品目は、ソルバーの数量どおりに、ちょうど使い切られる
- 月ごとの個数の合計は floor(N/12) か ceil(N/12) で、差は1個以内
- N が12以上なら、どの月も空にならない
- 数の少ない品目も、1年の中でばらけて出てくる（前半に何もない月ができない）
- 乱数を使わないので、同じ入力からは同じ結果になる
"""

import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTHS = 12


def allocate(result):
    """solve() の結果から、長さ12の月ごとの割り振りを返す。

    months[k] == [{"id": ..., "count": 正の整数}, ...]（品目 ID の順）
    """
    items = [(item["id"], item["count"]) for item in result["items"] if item["count"] > 0]
    total = sum(count for _, count in items)
    if total < MONTHS:
        raise ValueError(
            f"備蓄の個数の合計が {total} 個で、12か月のすべての月に割り振れません"
        )

    # 位置は分数で比べる（浮動小数点の誤差で順序が変わらないように）
    units = sorted(
        (Fraction(2 * j + 1, 2 * count), item_id)
        for item_id, count in items
        for j in range(count)
    )

    months = []
    for k in range(MONTHS):
        begin = k * total // MONTHS
        end = (k + 1) * total // MONTHS
        counts = {}
        for _, item_id in units[begin:end]:
            counts[item_id] = counts.get(item_id, 0) + 1
        months.append([{"id": item_id, "count": counts[item_id]} for item_id in sorted(counts)])
    return months


def _master():
    with open(ROOT / "data" / "items-master.json", encoding="utf-8") as f:
        return {item["id"]: item for item in json.load(f)["items"]}


def build_plan(household, template_id=None, exclude_tags=None, exclude_ids=None):
    """solve() と allocate() をまとめ、カレンダー用のデータを返す。"""
    from solver import solve

    result = solve(household, template_id, exclude_tags=exclude_tags, exclude_ids=exclude_ids)
    master = _master()
    return {
        "household": {
            "adults": household["adults"],
            "children": household["children"],
            "infants": household.get("infants", 0),
            "days": household["days"],
        },
        "template_id": template_id,
        "items": [
            {
                "id": item["id"],
                "name": master[item["id"]]["name"],
                "unit": master[item["id"]]["consume_unit"],
                "count": item["count"],
            }
            for item in result["items"]
        ],
        "months": allocate(result),
    }
