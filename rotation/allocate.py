"""12か月の消費の割り振りと、月ごとの消費日（Issue #22、#26）。

月への割り振り（allocate）の考え方：
1. 乳児用の品目（品目マスタの coeff_basis が infants）は、割り振りに入れない
   （普段の授乳で使った分を買い足す。オーナー決定 2026-11-12）。
2. 残りの品目を三つの組に分ける：主食・主菜／ほかの食べ物（副菜・間食など）／水。
3. 月ごとの個数を、次の三つの段で、どれも差が1個以内になるように決める。
     主食・主菜の数 ≤ 食べ物（水以外）の数 ≤ 全体の数
   1個多い月は、決まった順（MONTH_PRIORITY）の先頭から選ぶ。どの段も同じ順で選ぶので、
   多い月が段ごとに入れ子になり、「食べ物の数 ≤ 全体の数」などが必ず成り立つ。
4. 組ごとに、品目の1個1個を1年の中で等間隔の位置に置き（count 個なら (j + 0.5) / count）、
   位置の順に並べて、3. で決めた数ずつ1か月目から順に入れる。

こうすると、
- 各品目は、ソルバーの数量どおりに、ちょうど使い切られる
- 月ごとの個数の合計の差は1個以内
- 主食・主菜が12個以上なら、毎月1個以上。食べ物が24個以上なら、毎月2個以上
- 数の少ない品目も、1年の中でばらけて出てくる
- 乱数を使わないので、同じ入力からは同じ結果になる

消費日（schedule）の考え方：
- 1日に食べる食べ物（水以外）は、食べる人数（大人＋子供）× 2 個まで（一人一品・二品）。
- その月の食べ物が収まる最小の日数にし、日ごとの食べ物の数の差は1個以内にする。
- 品目は、なるべく同じ日にまとめる（家族で同じものを食べる）。主食・主菜から先に、
  空きのいちばん大きい日へ入れるので、主食・主菜も日ごとにばらける。水も同じように分ける。
"""

import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTHS = 12
PORTIONS_PER_PERSON_DAY = 2   # 一人一品・二品まで（オーナー決定 2026-11-12）
STAPLE_MAIN = ("staple", "main")

# 1個多くする月を選ぶ順。前から使うと、1年の中でばらける（1, 7, 4, 10, ... か月目）
MONTH_PRIORITY = (0, 6, 3, 9, 1, 7, 4, 10, 2, 8, 5, 11)


def _master():
    with open(ROOT / "data" / "items-master.json", encoding="utf-8") as f:
        return {item["id"]: item for item in json.load(f)["items"]}


def _is_infant(item):
    return item.get("coeff_basis") == "infants"


def _group(item):
    """0 = 主食・主菜、1 = ほかの食べ物、2 = 水"""
    if item["meal_role"] in STAPLE_MAIN:
        return 0
    if item["meal_role"] == "drink":
        return 2
    return 1


def _even_counts(total):
    """total 個を12か月に、差1個以内で分ける。多い月は MONTH_PRIORITY の先頭から。"""
    base, extra = divmod(total, MONTHS)
    counts = [base] * MONTHS
    for k in MONTH_PRIORITY[:extra]:
        counts[k] += 1
    return counts


def _spread(items, counts_per_month):
    """品目の1個1個を位置の順に並べ、月ごとの数ずつ順に入れる。"""
    units = sorted(
        (Fraction(2 * j + 1, 2 * count), item_id)
        for item_id, count in items
        for j in range(count)
    )
    months, start = [], 0
    for n in counts_per_month:
        months.append([item_id for _, item_id in units[start:start + n]])
        start += n
    return months


def allocate(result, master=None):
    """solve() の結果から、長さ12の月ごとの割り振りを返す。

    months[k] == [{"id": ..., "count": 正の整数}, ...]（品目 ID の順）。乳児用の品目は入れない。
    """
    master = master or _master()
    groups = ([], [], [])
    for item in result["items"]:
        if item["count"] > 0 and not _is_infant(master[item["id"]]):
            groups[_group(master[item["id"]])].append((item["id"], item["count"]))

    sizes = [sum(count for _, count in g) for g in groups]
    if sum(sizes) < MONTHS:
        raise ValueError(
            f"備蓄の個数の合計が {sum(sizes)} 個で、12か月のすべての月に割り振れません"
        )

    # 段ごとの月の数：主食・主菜 ≤ 食べ物 ≤ 全体（入れ子なので、組ごとの数は負にならない）
    staple_main = _even_counts(sizes[0])
    foods = _even_counts(sizes[0] + sizes[1])
    everything = _even_counts(sum(sizes))
    per_group = (
        staple_main,
        [f - s for f, s in zip(foods, staple_main)],
        [a - f for a, f in zip(everything, foods)],
    )

    spread = [_spread(g, counts) for g, counts in zip(groups, per_group)]
    months = []
    for k in range(MONTHS):
        counts = {}
        for g in spread:
            for item_id in g[k]:
                counts[item_id] = counts.get(item_id, 0) + 1
        months.append([{"id": item_id, "count": counts[item_id]} for item_id in sorted(counts)])
    return months


def _split_evenly(total, parts):
    base, extra = divmod(total, parts)
    return [base + (1 if d < extra else 0) for d in range(parts)]


def _fill(entries, capacities):
    """entries（[(id, count)]）を、空きのいちばん大きい日から順に入れる。"""
    days = [{} for _ in capacities]
    room = list(capacities)
    for item_id, count in entries:
        while count > 0:
            d = max(range(len(room)), key=lambda i: (room[i], -i))
            n = min(count, room[d])
            days[d][item_id] = days[d].get(item_id, 0) + n
            room[d] -= n
            count -= n
    return days


def schedule(result, household, master=None):
    """月ごとの消費日。長さ12で、days[k] は k か月目の消費日のリスト、
    各消費日は [{"id", "count"}]（品目 ID の順）。"""
    master = master or _master()
    eaters = household["adults"] + household["children"]
    limit = PORTIONS_PER_PERSON_DAY * max(1, eaters)

    plan = []
    for month in allocate(result, master):
        foods = [(e["id"], e["count"]) for e in month if _group(master[e["id"]]) < 2]
        drinks = [(e["id"], e["count"]) for e in month if _group(master[e["id"]]) == 2]
        n_foods = sum(c for _, c in foods)
        n_days = max(1, -(-n_foods // limit))

        # 主食・主菜を先に、数の多い品目から入れる（同じ品目をなるべく同じ日にまとめる）
        foods.sort(key=lambda e: (_group(master[e[0]]), -e[1], e[0]))
        drinks.sort(key=lambda e: (-e[1], e[0]))
        food_days = _fill(foods, _split_evenly(n_foods, n_days))
        drink_days = _fill(drinks, _split_evenly(sum(c for _, c in drinks), n_days))

        month_days = []
        for f, w in zip(food_days, drink_days):
            day = {**f, **w}
            month_days.append([{"id": i, "count": day[i]} for i in sorted(day)])
        plan.append(month_days)
    return plan


def build_plan(household, template_id=None, exclude_tags=None, exclude_ids=None):
    """solve()、allocate()、schedule() をまとめ、カレンダー用のデータを返す。"""
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
                "infant": _is_infant(master[item["id"]]),
            }
            for item in result["items"]
        ],
        "months": allocate(result, master),
        "days": schedule(result, household, master),
    }
