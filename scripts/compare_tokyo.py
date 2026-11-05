"""東京備蓄ナビとソルバーの結果を、同じ世帯条件で比べる報告を作る（Issue #13 段階2）。

比べるのは「多様性」と「栄養の条件」。栄養の判定は tests/harness_common.py の check_plan をそのまま使う。
東京の品目を品目マスタの代表品に置き換える対応は data/tokyo_bichiku_navi.json の master_mapping による（「近い」は仮）。
出力: reports/compare_tokyo.md（同じ内容を標準出力にも出す）

使い方: python3 scripts/compare_tokyo.py
"""
import itertools
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from harness_common import ROOT, check_plan, load_config, load_master, load_template_index  # noqa: E402

from comparison.tokyo_navi import load_config as load_tokyo_config  # noqa: E402
from comparison.tokyo_navi import tokyo_plan, tokyo_unquantified_items  # noqa: E402
from solver import solve  # noqa: E402

MAIN_TEMPLATE = "standard"
# テンプレートと除外条件で構成が変わることを示す例の世帯
EXAMPLE = {"adults": 2, "children": 1, "infants": 0, "days": 3}
# 例の世帯で試す除外条件（exclude_tags, exclude_ids）。standard の品目に当たるものを選んだ
EXAMPLE_EXCLUSIONS = [(["needs-heat"], []), (["needs-water"], []), ([], ["M006"])]
# 報告に載せる check_plan の判定（栄養の条件に当たるもの）
NUTRITION_CHECKS = {
    "エネルギーが目標以上": "E≥",
    "エネルギーが過剰でない": "E≤",
    "たんぱく質が目標以上": "P≥",
    "水が必要量どおり（不足も過剰もない）": "水",
}
MARK = {True: "OK", False: "NG", None: "—"}
TOKYO_PREFIX = "tokyo-"


def household_label(hh):
    label = f"大人{hh['adults']} 子供{hh['children']}"
    if hh.get("infants"):
        label += f" 乳幼児{hh['infants']}"
    return f"{label} / {hh['days']}日"


def iter_households(config):
    cases = config["cases"]
    for adults, children, infants, days in itertools.product(
            cases["adults"], cases["children"], cases["infants"], cases["days"]):
        yield {"adults": adults, "children": children, "infants": infants, "days": days}


# --- 東京の品目を、品目マスタの代表品に置き換える -------------------------------------------

def conversion_factor(basis, item):
    """東京の1単位が、品目マスタの何単位に当たるか。品目マスタの値だけを使う。"""
    if basis == "count":
        return 1
    if basis == "weight":   # 東京の kg → g → マスタの1単位の重さ（unit_gram）で割る
        return 1000 / item["unit_gram"]
    if basis == "volume":   # 東京の L → mL → マスタの1単位の水の量（water_per_unit）で割る
        return 1000 / item["water_per_unit"]
    raise ValueError(basis)


def as_tokyo_item(tokyo_id, tokyo_item, mapping, master, master_id):
    """東京の1単位を1単位とする、仮の品目（メモリ上だけ）。栄養値は代表品 × 換算係数。"""
    rep = master[master_id]
    factor = conversion_factor(mapping["basis"], rep)
    protein = rep.get("protein_per_unit")
    return {
        **rep,
        "id": TOKYO_PREFIX + tokyo_id,
        "name": f"{tokyo_item['name']}（{rep['name']}で換算）",
        "consume_unit": tokyo_item["unit"],
        "cal_per_unit": rep["cal_per_unit"] * factor,
        "protein_per_unit": None if protein is None else protein * factor,
        "water_per_unit": (rep.get("water_per_unit") or 0) * factor,
        "units_per_serving": (rep.get("units_per_serving") or 1) / factor,
        "pack_size": 1,
    }


def build_tokyo_master(tconf, master, choose=None):
    """数量を換算できる東京の品目だけの、仮の品目マスタ。choose で代表品を差し替えられる。"""
    tokyo_items = {item["id"]: item for item in tconf["items"]}
    view = {}
    for tokyo_id, mapping in tconf["master_mapping"]["items"].items():
        if "basis" not in mapping:
            continue
        master_id = (choose or {}).get(tokyo_id, mapping["representative"])
        view[TOKYO_PREFIX + tokyo_id] = as_tokyo_item(tokyo_id, tokyo_items[tokyo_id], mapping, master, master_id)
    return view


def tokyo_as_plan(quantities, view):
    return {"items": [{"id": TOKYO_PREFIX + tid, "count": q} for tid, q in quantities.items()
                      if TOKYO_PREFIX + tid in view]}


# --- 集計 -------------------------------------------------------------------------------------

def totals(plan, master):
    """通常の食品（特別食を除く）の kcal とたんぱく質の合計。たんぱく質の値がない品目は 0g（check_plan と同じ扱い）。"""
    kcal = protein = 0.0
    for entry in plan["items"]:
        item = master[entry["id"]]
        if item["daily_coeff"] is not None:
            continue
        kcal += item["cal_per_unit"] * entry["count"]
        protein += (item.get("protein_per_unit") or 0) * entry["count"]
    return kcal, protein


def per_person_day(value, hh, factor):
    """大人換算の1人1日あたり。子供は factor 倍で数え、乳幼児は数えない（目標と同じ数え方）。"""
    return value / ((hh["adults"] + factor * hh["children"]) * hh["days"])


def nutrition_marks(plan, hh, template_id, master, config):
    results = {name: ok for name, ok, _ in check_plan(plan, hh, template_id, master, config)}
    return " ".join(f"{label}{MARK[results[name]]}" for name, label in NUTRITION_CHECKS.items())


def count_ng(plan, hh, template_id, master, config):
    return sum(1 for name, ok, _ in check_plan(plan, hh, template_id, master, config)
               if name in NUTRITION_CHECKS and ok is False)


# --- 報告 -------------------------------------------------------------------------------------

def mapping_section(tconf, master):
    tokyo_items = {item["id"]: item for item in tconf["items"]}
    rows = []
    for tokyo_id, m in tconf["master_mapping"]["items"].items():
        item = tokyo_items[tokyo_id]
        if "basis" in m:
            rep = master[m["representative"]]
            factor = conversion_factor(m["basis"], rep)
            how = f"{m['representative']} {rep['name']}（東京の1{item['unit']} ＝ {factor:g} {rep['consume_unit']}）"
            note = m.get("note", "")
        else:
            cands = "、".join(m.get("candidates", [])) or "—"
            how = f"計算に入れない（候補 {cands}）"
            note = m.get("reason", "")
        rows.append(f"| {tokyo_id} | {item['name']} | {item['unit']} | {m['status']} | {how} | {note} |")
    return [
        "## 東京の品目と品目マスタの対応",
        "",
        "`data/tokyo_bichiku_navi.json` の `master_mapping`。候補は `docs/tokyo_bichiku_navi.md` の 7.3。",
        "**「近い（仮）」の代表品は仮に決めたもので、オーナーの判断事項です。**",
        "換算は品目マスタの値（`unit_gram`、`water_per_unit`）だけを使い、合と g などの外部の換算は使っていません。",
        "",
        "| 東京 id | 東京の品目 | 東京の単位 | 対応 | 栄養の計算に使う代表品 | 備考 |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]


def representative_range(tconf, master, quantities, hh, config):
    """「近い（仮）」の品目の代表品を、候補の中で入れ替えたときの、1人1日あたりの kcal とたんぱく質の幅。"""
    choices = {tid: m["candidates"] for tid, m in tconf["master_mapping"]["items"].items()
               if "basis" in m and len(m["candidates"]) > 1 and m["status"].startswith("近い")}
    kcal_values, protein_values = [], []
    for combo in itertools.product(*choices.values()):
        view = build_tokyo_master(tconf, master, dict(zip(choices, combo)))
        kcal, protein = totals(tokyo_as_plan(quantities, view), view)
        kcal_values.append(per_person_day(kcal, hh, config["energy"]["child_factor"]))
        protein_values.append(per_person_day(protein, hh, config["protein"]["child_factor"]))
    return (min(kcal_values), max(kcal_values)), (min(protein_values), max(protein_values))


def build_report():
    master = load_master()
    config = load_config()
    tconf = load_tokyo_config()
    tokyo_view = build_tokyo_master(tconf, master)
    tokyo_names = {item["id"]: item["name"] for item in tconf["items"]}
    templates = [t["id"] for t in load_template_index()]
    households = list(iter_households(config))

    nutrition_rows, total_rows, range_rows = [], [], []
    tokyo_sets, solver_sets = {}, {t: {} for t in templates}
    kinds_rows = []
    tokyo_ng = solver_ng = 0
    tokyo_ppd, solver_ppd = [], []
    failures = []

    for hh in households:
        label = household_label(hh)
        # 東京
        quantities = tokyo_plan(hh)
        unquantified = tokyo_unquantified_items(hh)
        tokyo_sets[label] = frozenset(quantities) | frozenset(unquantified)
        t_plan = tokyo_as_plan(quantities, tokyo_view)
        t_kcal, t_protein = totals(t_plan, tokyo_view)
        tokyo_ng += bool(count_ng(t_plan, hh, None, tokyo_view, config))
        # ソルバー（全テンプレート。栄養の表は standard）
        plans = {}
        for template_id in templates:
            try:
                plans[template_id] = solve(household=hh, template_id=template_id, exclude_tags=[], exclude_ids=[])
            except Exception as e:  # noqa: BLE001（解けない条件も報告に残す）
                failures.append(f"{template_id} / {label}: {type(e).__name__}: {e}")
                continue
            solver_sets[template_id][label] = frozenset(e["id"] for e in plans[template_id]["items"] if e["count"] > 0)
        s_plan = plans.get(MAIN_TEMPLATE)

        ef, pf = config["energy"]["child_factor"], config["protein"]["child_factor"]
        t_k, t_p = per_person_day(t_kcal, hh, ef), per_person_day(t_protein, hh, pf)
        tokyo_ppd.append((t_k, t_p))
        t_marks = nutrition_marks(t_plan, hh, None, tokyo_view, config)
        if s_plan is not None:
            s_kcal, s_protein = totals(s_plan, master)
            s_k, s_p = per_person_day(s_kcal, hh, ef), per_person_day(s_protein, hh, pf)
            solver_ppd.append((s_k, s_p))
            s_marks = nutrition_marks(s_plan, hh, MAIN_TEMPLATE, master, config)
            solver_ng += bool(count_ng(s_plan, hh, MAIN_TEMPLATE, master, config))
            s_cells = (f"{s_k:,.0f}", f"{s_p:.1f}", s_marks, f"{s_kcal:,.0f}", f"{s_protein:,.1f}")
        else:
            s_cells = ("解なし",) * 5
        nutrition_rows.append(f"| {label} | {t_k:,.0f} | {s_cells[0]} | {t_p:.1f} | {s_cells[1]} | {t_marks} | {s_cells[2]} |")
        total_rows.append(f"| {label} | {t_kcal:,.0f} | {s_cells[3]} | {t_protein:,.1f} | {s_cells[4]} |")
        (k_lo, k_hi), (p_lo, p_hi) = representative_range(tconf, master, quantities, hh, config)
        range_rows.append(f"| {label} | {k_lo:,.0f}〜{k_hi:,.0f} | {p_lo:.1f}〜{p_hi:.1f} |")
        kinds = [str(len(solver_sets[t].get(label, ()))) if label in solver_sets[t] else "解なし" for t in templates]
        kinds_rows.append(f"| {label} | {len(tokyo_sets[label])} | " + " | ".join(kinds) + " |")

    n = len(households)
    target_e = config["energy"]["adult_kcal_per_day"]
    target_p = config["protein"]["adult_g_per_day"]

    def span(values, i, fmt):
        return f"{fmt.format(min(v[i] for v in values))}〜{fmt.format(max(v[i] for v in values))}"

    # 多様性：条件を変えたときに構成が変わるか
    def distinct(sets):
        return len(set(sets.values()))

    tokyo_all = set().union(*tokyo_sets.values())
    tokyo_common = set.intersection(*map(set, tokyo_sets.values()))
    tokyo_varying = sorted(tokyo_all - tokyo_common, key=int)
    infant_dependent = all(
        (tokyo_sets[household_label(hh)] - tokyo_common) == (frozenset(tokyo_varying) if hh["infants"] else frozenset())
        for hh in households)
    all_solver_sets = [s for t in templates for s in solver_sets[t].values()]
    per_template = [distinct(solver_sets[t]) for t in templates]
    # 乳幼児がいるときに、乳幼児の食品（特別食で、乳幼児の人数で数えるもの）を出すテンプレート
    infant_food = {i for i, item in master.items() if item.get("coeff_basis") == "infants"}
    infant_templates = [t for t in templates if any(s & infant_food for s in solver_sets[t].values())]
    distinct_rows = [f"| 東京備蓄ナビ | {distinct(tokyo_sets)} / {n} | {len(tokyo_all)} |"]
    for t in templates:
        union = set().union(*solver_sets[t].values()) if solver_sets[t] else set()
        distinct_rows.append(f"| ソルバー {t} | {distinct(solver_sets[t])} / {len(solver_sets[t])} | {len(union)} |")
    distinct_rows.append(f"| ソルバー 全テンプレート | {len(set(all_solver_sets))} / {len(all_solver_sets)} | "
                         f"{len(set().union(*all_solver_sets))} |")

    # 例の世帯：テンプレートと除外条件による違い
    example_rows = []
    for t in templates:
        plan = solve(household=EXAMPLE, template_id=t, exclude_tags=[], exclude_ids=[])
        ids = [e["id"] for e in plan["items"] if e["count"] > 0]
        example_rows.append(f"| {t} | なし | {len(ids)} | {', '.join(ids)} |")
    for tags, exclude_ids in EXAMPLE_EXCLUSIONS:
        what = "、".join([f"タグ {t}" for t in tags] + [f"品目 {i}" for i in exclude_ids])
        try:
            plan = solve(household=EXAMPLE, template_id=MAIN_TEMPLATE, exclude_tags=tags, exclude_ids=exclude_ids)
        except Exception as e:  # noqa: BLE001
            example_rows.append(f"| {MAIN_TEMPLATE} | {what} | 解なし | {type(e).__name__} |")
            continue
        ids = [e["id"] for e in plan["items"] if e["count"] > 0]
        example_rows.append(f"| {MAIN_TEMPLATE} | {what} | {len(ids)} | {', '.join(ids)} |")
    example_tokyo = sorted(tokyo_sets[household_label(EXAMPLE)], key=int)
    example_q = tokyo_plan(EXAMPLE)
    example_plan = tokyo_as_plan(example_q, tokyo_view)
    example_kcal, _ = totals(example_plan, tokyo_view)
    breakdown_rows = []
    for entry in example_plan["items"]:
        item = tokyo_view[entry["id"]]
        kcal = item["cal_per_unit"] * entry["count"]
        protein = (item.get("protein_per_unit") or 0) * entry["count"]
        breakdown_rows.append(f"| {item['name']} | {entry['count']} {item['consume_unit']} | {kcal:,.0f} | "
                              f"{kcal / example_kcal:.0%} | {protein:,.1f} |")

    excluded = [(tid, m) for tid, m in tconf["master_mapping"]["items"].items() if "basis" not in m]
    no_match = [tid for tid, m in excluded if m["status"] == "対応なし"]
    staple_kcal = sum(tokyo_view[TOKYO_PREFIX + tid]["cal_per_unit"] * example_q[tid]
                      for tid in example_q if TOKYO_PREFIX + tid in tokyo_view
                      and tokyo_view[TOKYO_PREFIX + tid]["meal_role"] == "staple")
    # 乳幼児を加えると、水と乳幼児の食品以外の数量も変わる条件
    infant_shift = []
    for hh in households:
        if not hh["infants"]:
            continue
        with_infants, without = tokyo_plan(hh), tokyo_plan({**hh, "infants": 0})
        if any(with_infants.get(tid) != q for tid, q in without.items() if tid != "1"):
            infant_shift.append(household_label(hh))
    tentative = [(tid, m) for tid, m in tconf["master_mapping"]["items"].items() if m["status"].startswith("近い")]

    lines = [
        "# 東京備蓄ナビとソルバーの比較",
        "",
        f"作成日：{date.today().isoformat()}　／　`python3 scripts/compare_tokyo.py` の出力",
        "",
        "## 要約",
        "",
        f"世帯条件は `tests/sanity_config.json` の `cases`（{n} 通り）。ソルバーの栄養は `{MAIN_TEMPLATE}` テンプレート。",
        "",
        "**栄養の条件**（判定は `tests/harness_common.py` の `check_plan`。目標は大人 "
        f"{target_e:,} kcal・たんぱく質 {target_p} g／人日で、仮の値）",
        "",
        f"- 東京：大人換算 1人1日あたり {span(tokyo_ppd, 0, '{:,.0f}')} kcal、たんぱく質 {span(tokyo_ppd, 1, '{:.1f}')} g。"
        f"栄養の判定（E≥・E≤・P≥・水）に NG があったのは {tokyo_ng} / {n} 通り。",
        f"  - 東京の {len(no_match)} 品目（{', '.join(tokyo_names[t] for t in no_match)}）は、品目マスタに対応がないか、1単位の大きさが分からないので、計算に入っていない。したがって東京の kcal とたんぱく質は**下限の値**である。それでも、多くの条件でエネルギーが目標の上限を超えた。",
        f"  - 主な理由は、主食が重なっていること（docs の 3.4 のとおり、レトルトご飯 1日3食と無洗米 1日 0.375 kg が別々に足される）。例の世帯（{household_label(EXAMPLE)}）では、計算に入れた kcal の {staple_kcal / example_kcal:.0%} が主食である（下の内訳）。",
        f"- ソルバー（{MAIN_TEMPLATE}）：1人1日あたり {span(solver_ppd, 0, '{:,.0f}')} kcal、たんぱく質 {span(solver_ppd, 1, '{:.1f}')} g。"
        f"NG は {solver_ng} / {len(solver_ppd)} 通り。",
        "",
        "**多様性**",
        "",
        f"- 東京：{n} 通りの条件で、品目の構成は {distinct(tokyo_sets)} 種類だけ。"
        + (f"変わるのは乳幼児の有無だけで、乳幼児がいると {', '.join(tokyo_names[i] for i in tokyo_varying)} が加わる。"
           if infant_dependent else f"条件によって出入りする品目：{', '.join(tokyo_varying)}。")
        + "数量は人数と日数で増えるが、品目は変わらない。",
        f"- ソルバー：同じ {n} 通りで、{MAIN_TEMPLATE} だけでも構成は {distinct(solver_sets[MAIN_TEMPLATE])} 種類。"
        f"{len(templates)} テンプレート全体では {len(set(all_solver_sets))} 種類。**テンプレートを固定すると、ソルバーも世帯の規模では構成がほとんど変わらない**"
        f"（テンプレートごとに {min(per_template)}〜{max(per_template)} 種類）。構成の違いは、主にテンプレートと除外条件から生じる（下の例）。",
        f"- ソルバーが乳幼児の食品（{', '.join(sorted(infant_food))}）を出したのは、{', '.join(infant_templates) or 'どのテンプレートでもない'}"
        f"{' テンプレートだけ' if infant_templates else ''}。ほかのテンプレートでは、乳幼児がいても水が増えるだけである。東京は乳幼児がいると必ずミルクなどを出す。",
        "- 品目の粒度が違う点に注意：東京の品目は「レトルト食品」のような区分で、ソルバーは品目マスタの具体的な品目。種類数をそのまま比べることはできない。",
        "",
        *([f"**解けなかった条件**：{len(failures)} 件", "", *[f"- {f}" for f in failures], ""] if failures else []),
        *mapping_section(tconf, master),
        "## 栄養の条件",
        "",
        "1人1日あたりは**大人換算**：合計 ÷ ｛（大人 ＋ 係数 × 子供）× 日数｝。係数は `tests/sanity_config.json` の "
        f"`child_factor`（エネルギー {config['energy']['child_factor']}、たんぱく質 {config['protein']['child_factor']}）。"
        "乳幼児は、目標と同じく数えない（ミルクなどの特別食は別計算で、ここには入れない）。",
        "目標が変わっても読み直せるように、合否だけでなく実数を並べる。",
        "たんぱく質の値がない品目は、`check_plan` と同じく 0g として足している。",
        "",
        "判定：E≥ エネルギーが目標以上、E≤ エネルギーが目標の "
        f"{config['energy']['max_ratio_to_target']} 倍以下、P≥ たんぱく質が目標以上、水 必要量どおり。",
        "",
        "| 条件 | 東京 kcal/人日 | ソルバー kcal/人日 | 東京 たんぱく質 g/人日 | ソルバー たんぱく質 g/人日 | 東京の判定 | ソルバーの判定 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *nutrition_rows,
        "",
        "### 合計（世帯全体・全日数）",
        "",
        "| 条件 | 東京 kcal | ソルバー kcal | 東京 たんぱく質 g | ソルバー たんぱく質 g |",
        "| --- | --- | --- | --- | --- |",
        *total_rows,
        "",
        f"### 東京の内訳（例：{household_label(EXAMPLE)}）",
        "",
        "計算に入れた品目だけ。割合は、計算に入れた kcal に占める割合。",
        "",
        "| 東京の品目（代表品） | 数量 | kcal | 割合 | たんぱく質 g |",
        "| --- | --- | --- | --- | --- |",
        *breakdown_rows,
        "",
        *(["### 乳幼児がいると、東京の通常の食品の数量も変わる条件", "",
           "東京の乾麺・お菓子・果物の缶詰は、世帯の人数（5人以下か6人以上か）で決まる固定値で、この再現では乳幼児も人数に数えている"
           "（docs に記録がなく、**不明**）。そのため、次の条件では、乳幼児の有無で果物の缶詰の数量が変わり、kcal も変わる。", "",
           *[f"- {label}" for label in infant_shift], ""] if infant_shift else []),
        "### 代表品を入れ替えたときの、東京の値の幅",
        "",
        "「近い（仮）」の品目（"
        + "、".join(f"{tokyo_names[tid]}：{'・'.join(m['candidates'])}" for tid, m in tentative)
        + "）の代表品を、候補の中で入れ替えたときの、大人換算 1人1日あたりの最小〜最大。"
        "たんぱく質の値がない候補は 0g として計算している。",
        "",
        "| 条件 | kcal/人日 | たんぱく質 g/人日 |",
        "| --- | --- | --- |",
        *range_rows,
        "",
        "## 多様性",
        "",
        "### 条件を変えたときに、品目の構成が変わるか",
        "",
        "構成 ＝ 選ばれた品目の集合（数量は見ない）。東京は「適宜」「適量」の品目も含め、東京の品目 id で数える。",
        "",
        "| 方式 | 構成の種類 / 条件の数 | 現れた品目の種類 |",
        "| --- | --- | --- |",
        *distinct_rows,
        "",
        "### 条件ごとの品目の種類数",
        "",
        "| 条件 | 東京 | " + " | ".join(f"ソルバー {t}" for t in templates) + " |",
        "| --- | --- | " + " | ".join("---" for _ in templates) + " |",
        *kinds_rows,
        "",
        f"### 例：{household_label(EXAMPLE)} で、テンプレートと除外条件を変える",
        "",
        f"東京は、この世帯では常に {len(example_tokyo)} 品目（{', '.join(tokyo_names[i] for i in example_tokyo)}）。"
        "東京には、テンプレートや除外条件に当たる入力がない。",
        "",
        "| テンプレート | 除外 | 品目の種類数 | 品目 |",
        "| --- | --- | --- | --- |",
        *example_rows,
        "",
        "## 計算から外した東京の品目",
        "",
        *[f"- {tid} {tokyo_names[tid]}：{m['status']}。{m.get('reason', '')}" for tid, m in excluded],
        "",
    ]
    return "\n".join(lines)


def main():
    report = build_report()
    out = ROOT / "reports" / "compare_tokyo.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n→ {out.relative_to(ROOT)} に保存しました")


if __name__ == "__main__":
    main()
