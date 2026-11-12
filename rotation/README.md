# 12か月の消費の割り振り（rotation）

ソルバーの結果（品目と数量）を、12か月に割り振ります。印刷カレンダー（`calender.html`）は、この結果を表示します。

```python
from solver import solve
from rotation import allocate, build_plan

months = allocate(solve(household, "standard"))   # 長さ12。months[0] は計画の1か月目
plan = build_plan(household, "standard", exclude_tags=[], exclude_ids=[])
# plan == {"household": {...}, "template_id": ..., "items": [{"id", "name", "unit", "count"}], "months": months}
```

## 割り振りの方法

1. 品目ごとに、その品目の1個1個を、1年の中で等間隔の位置に置く（`count` 個なら `(j + 0.5) / count`）。
2. すべての品目の1個1個を、位置の順に一列に並べる（同じ位置なら品目 ID の順）。
3. 一列を、個数がなるべく等しい12の区間に、順に切る。

これで、ソルバーの数量どおりに使い切り、月ごとの個数の合計の差は1個以内、どの月にも食べるものがあり、
数の少ない品目も1年の中でばらけます。乱数は使わないので、同じ入力からは同じ結果になります。
個数の合計が12未満のときは、空の月ができるので `ValueError` にします。

## カレンダー用のデータ

```bash
python3 scripts/build_plan.py --adults 2 --children 1 --infants 1 --days 7 --template baby --name a2c1i1-7d-baby
# → plans/a2c1i1-7d-baby.js（window.ROLLING_PLAN = {...};）
```

`calender.html?plan=a2c1i1-7d-baby&start=2026-12-01` で開きます（`start` の月が計画の1か月目）。
`file://` で開いても動くように、JSON ではなく JS で出力します。

**参加者の世帯は `--out-dir private/plans` に出力し、コミットしません。**
開くときは `calender.html` を `private/` に写し、`private/calender.html?plan=<名前>` で開きます（`private/` は `.gitignore` 済み）。
