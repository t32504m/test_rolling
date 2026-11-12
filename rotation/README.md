# 12か月の消費の割り振り（rotation）

ソルバーの結果（品目と数量）を、12か月に割り振ります。印刷カレンダー（`calender.html`）は、この結果を表示します。

```python
from solver import solve
from rotation import allocate, schedule, build_plan

result = solve(household, "standard")
months = allocate(result)            # 長さ12。months[0] は計画の1か月目。乳児用の品目は入れない
days = schedule(result, household)   # 長さ12。days[k] は k か月目の消費日のリスト。各消費日は [{"id", "count"}]
plan = build_plan(household, "standard", exclude_tags=[], exclude_ids=[])
# plan == {"household": {...}, "template_id": ..., "items": [{"id", "name", "unit", "count", "infant"}],
#          "months": months, "days": days}
```

## 月への割り振りの方法（allocate）

1. 乳児用の品目（品目マスタの `coeff_basis` が `infants`）は入れない。普段の授乳で使った分を買い足す（オーナー決定 2026-11-12）。
2. 残りの品目を、主食・主菜／ほかの食べ物／水の三つの組に分ける。
3. 月ごとの個数を「主食・主菜の数 ≤ 食べ物（水以外）の数 ≤ 全体の数」の三つの段で、どれも差が1個以内になるように決める。
   1個多い月は、どの段も同じ決まった順で選ぶので、段の間で数が逆転しない。
4. 組ごとに、品目の1個1個を1年の中で等間隔の位置に置き（`count` 個なら `(j + 0.5) / count`）、位置の順に、3. の数ずつ月に入れる。

これで、ソルバーの数量どおりに使い切り、月ごとの個数の合計の差は1個以内、
主食・主菜が12個以上なら毎月1個以上、食べ物が24個以上なら毎月2個以上になり、数の少ない品目も1年の中でばらけます。
乱数は使わないので、同じ入力からは同じ結果になります。個数の合計が12未満のときは、空の月ができるので `ValueError` にします。

## 消費日（schedule）

- 1日に食べる食べ物（水以外）は、食べる人数（大人＋子供）× 2 個まで（一人一品・二品）。
- その月の食べ物が収まる最小の日数（`ceil(食べ物 ÷ (人数×2))`、最低1日）にし、日ごとの食べ物の数の差は1個以内にする。
- 主食・主菜から先に、数の多い品目から、空きのいちばん大きい日へ入れる。同じ品目はなるべく同じ日にまとまり、主食・主菜は日ごとにばらける。水も同じように分ける。

カレンダーは、決めた曜日（例：第2火曜日）から続く日を、消費日の数だけ印を付けます。
消費日が2日以上の月は、STOCK の欄を日ごとにまとめ、その日の日付を頭に置きます。

## カレンダー用のデータ

```bash
python3 scripts/build_plan.py --adults 2 --children 1 --infants 1 --days 7 --template baby --name a2c1i1-7d-baby
# → plans/a2c1i1-7d-baby.js（window.ROLLING_PLAN = {...};）
```

`calender.html?plan=a2c1i1-7d-baby&start=2026-12-01` で開きます（`start` の月が計画の1か月目）。
`file://` で開いても動くように、JSON ではなく JS で出力します。

**参加者の世帯は `--out-dir private/plans` に出力し、コミットしません。**
開くときは `calender.html` を `private/` に写し、`private/calender.html?plan=<名前>` で開きます（`private/` は `.gitignore` 済み）。
