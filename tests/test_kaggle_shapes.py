"""Regression tests for problems found by running vizdesk on popular Kaggle datasets
(Telco churn, Titanic, Netflix, Superstore, S&P 500, California housing, Wine reviews).

Each test builds a small table with the same shape as the real one, so the
suite needs no downloads. test_real_kaggle_datasets runs on the real files
when they are present in datasets/kaggle/.
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vizdesk.cleaning import apply_steps, suggest_cleaning
from vizdesk.data import find_data_files, profile
from vizdesk.render import render_figure
from vizdesk.spec import FigureSpec
from vizdesk.suggest import find_target, suggest

ROOT = Path(__file__).resolve().parents[1]
rng = np.random.default_rng(7)


def _suggest(df, goal="explore", limit=12, **kw):
    prof = profile(df)
    return prof, suggest(prof, goal, df, limit=limit, **kw)


def _draws(df, panels, tmp_path):
    spec = FigureSpec(source="memory", panels=panels, rows=3, cols=4, dpi=40, output=str(tmp_path / "f.png"))
    return render_figure(df, spec).warnings


def test_telco_blank_numbers_and_churn_target(tmp_path):
    n = 600
    contract = rng.choice(["Month-to-month", "One year", "Two year"], n)
    churn = np.where(rng.random(n) < np.select([contract == "Month-to-month"], [0.45], 0.05), "Yes", "No")
    total = [f"{v:.2f}" for v in rng.uniform(20, 8000, n)]
    total[:5] = [" "] * 5  # TotalCharges is text with blanks in the real file
    df = pd.DataFrame({"customerID": [f"{i:04d}-ABCDE" for i in range(n)], "Contract": contract, "tenure": rng.integers(0, 73, n),
                       "MonthlyCharges": rng.uniform(18, 120, n), "TotalCharges": total, "Churn": churn})
    prof = profile(df)
    assert prof.get("customerID").kind == "identifier"
    tc = prof.get("TotalCharges")
    assert tc.numeric_like and tc.blanks == 5
    steps = {s.action: s for s in suggest_cleaning(prof)}
    assert "only spaces" in steps["strip_whitespace"].reason and "'" in steps["to_numeric"].reason
    clean = apply_steps(df, [s for s in suggest_cleaning(prof) if s.safe])
    assert clean["TotalCharges"].isna().sum() == 5
    target = find_target(profile(clean), clean)
    assert (target.column, target.positive) == ("Churn", "Yes")
    _, panels = _suggest(clean, "target")
    rate = [p for p in panels if p.chart == "stacked_bar_100" and p.x == "Contract"]
    assert rate and rate[0].hue == "Churn" and "Month-to-month" in rate[0].reason
    assert not any(p.x == "Churn" and p.chart == "bar_chart" for p in _suggest(clean, "comparison")[1])
    assert _draws(clean, panels, tmp_path) == []


def test_titanic_codes_ordinals_and_order(tmp_path):
    n = 400
    df = pd.DataFrame({"PassengerId": range(1, n + 1), "Survived": rng.integers(0, 2, n), "Pclass": rng.choice([1, 2, 3], n),
                       "Sex": rng.choice(["male", "female"], n), "Age": rng.normal(30, 14, n).clip(0.5),
                       "Ticket": [f"A/5 {rng.integers(1000, 99999)}" for _ in range(n)],
                       "Cabin": [f"C{rng.integers(1, 150)}" if rng.random() < 0.3 else None for _ in range(n)]})
    prof = profile(df)
    assert prof.get("Ticket").kind == "identifier"
    assert prof.get("Pclass").ordinal and prof.get("Pclass").kind == "categorical"
    assert find_target(prof, df).column == "Survived"
    steps = {s.action for s in suggest_cleaning(prof)}
    assert "bin" in steps  # Age into ranges, like the notebooks' AgeBin
    _, panels = _suggest(df, "target")
    pclass = next(p for p in panels if p.x == "Pclass")
    assert pclass.options.get("order") == "label"
    assert _draws(df, panels, tmp_path) == []


def test_netflix_lists_units_years_and_text_dates(tmp_path):
    n = 500
    genres = ["Dramas", "Comedies", "Documentaries", "International Movies", "Thrillers", "Kids' TV"]
    df = pd.DataFrame({
        "show_id": [f"s{i}" for i in range(n)],
        "type": rng.choice(["Movie", "TV Show"], n, p=[0.7, 0.3]),
        "listed_in": [", ".join(rng.choice(genres, rng.integers(1, 4), replace=False)) for _ in range(n)],
        "date_added": [f" {m} {d}, {y}" for m, d, y in zip(rng.choice(["January", "March", "July"], n), rng.integers(1, 28, n),
                                                            rng.integers(2015, 2022, n))],
        "release_year": rng.integers(1990, 2022, n),
        "duration": [f"{rng.integers(60, 180)} min" if rng.random() < 0.7 else f"{rng.integers(1, 6)} Seasons" for _ in range(n)],
        "description": ["A young detective uncovers a family secret while the city prepares for a storm."] * n,
    })
    prof = profile(df)
    assert prof.get("listed_in").multi_valued and prof.get("listed_in").item_unique == len(genres)
    assert prof.get("duration").units == ["min", "season"]
    assert prof.get("release_year").is_year and not prof.get("release_year").is_measure
    assert prof.get("date_added").datetime_like
    clean = apply_steps(df, suggest_cleaning(prof))
    assert {"duration_value", "duration_unit", "date_added_year"} <= set(clean.columns)
    cprof, panels = _suggest(clean, "explore")
    assert find_target(cprof, clean) is None  # duration_value mixes units: never a target
    split = [p for p in suggest(cprof, "ranking", clean) if p.options.get("split") == "listed_in"]
    assert split
    assert any(p.chart == "line_graph" and p.x == "date_added" and not p.y for p in suggest(cprof, "trend", clean))
    assert all(p.y != "duration_value" or p.options.get("filter") for p in panels)
    assert _draws(clean, panels + split, tmp_path) == []


def test_superstore_hierarchy_ids_and_totals(tmp_path):
    n = 800
    sub = {"Furniture": ["Chairs", "Tables", "Bookcases"], "Technology": ["Phones", "Copiers", "Machines"],
           "Office Supplies": ["Binders", "Paper", "Art", "Storage"]}
    cat = rng.choice(list(sub), n)
    df = pd.DataFrame({"Order ID": [f"CA-2016-{rng.integers(100000, 999999)}" for _ in range(n)],
                       "Customer ID": [f"CG-{rng.integers(10000, 10400)}" for _ in range(n)],
                       "Postal Code": rng.integers(10000, 99999, n), "Category": cat,
                       "Sub-Category": [rng.choice(sub[c]) for c in cat],
                       "Sales": rng.lognormal(4, 1.2, n), "Profit": rng.normal(20, 80, n)})
    prof = profile(df)
    assert {prof.get(c).kind for c in ("Order ID", "Customer ID", "Postal Code")} == {"identifier"}
    _, panels = _suggest(df, "composition")
    sun = [p for p in panels if p.chart == "sunburst_diagram"]
    assert sun and sun[0].columns == ["Category", "Sub-Category"]
    assert all(p.y in (None, "Sales") for p in panels)  # shares of a total, never of Profit (negative) or a mean
    assert _draws(df, panels, tmp_path) == []


def test_stock_panel_data_filters_one_ticker(tmp_path):
    days = pd.bdate_range("2015-01-01", periods=120)
    frames = []
    for i, name in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ", "KKK"]):
        close = 50 + i * 10 + np.cumsum(rng.normal(0, 1, len(days)))
        frames.append(pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "open": close + 0.3, "high": close + 1, "low": close - 1,
                                    "close": close, "volume": rng.integers(1e5, 1e6, len(days)) * (10 if name == "CCC" else 1),
                                    "Name": name}))
    df = pd.concat(frames, ignore_index=True)
    prof = profile(df)
    clean = apply_steps(df, [s for s in suggest_cleaning(prof) if s.safe])
    _, panels = _suggest(clean, "explore", 8)
    assert panels[0].chart == "candlestick_chart" and panels[0].options["filter"] == "Name=CCC"  # the most traded
    assert not any(p.chart in ("scatterplot", "hexbin_plot", "correlation_heatmap") for p in panels)
    assert _draws(clean, panels, tmp_path) == []


def test_housing_caps_maps_and_no_mean_shares(tmp_path):
    n = 2000
    value = rng.lognormal(12, 0.5, n).clip(max=500001)
    value[:120] = 500001
    df = pd.DataFrame({"longitude": rng.uniform(-124, -114, n), "latitude": rng.uniform(32, 42, n),
                       "population": rng.lognormal(7, 0.8, n).round(), "median_income": rng.lognormal(1.3, 0.4, n),
                       "median_house_value": value, "ocean_proximity": rng.choice(["INLAND", "NEAR BAY", "<1H OCEAN"], n)})
    prof = profile(df)
    assert prof.get("median_house_value").capped_pct >= 5
    assert any(s.action == "drop_capped" for s in suggest_cleaning(prof))
    _, panels = _suggest(df, "explore")
    geo = next(p for p in panels if p.chart in ("bubble_map", "dot_map"))
    assert geo.hue == "median_house_value" and geo.size in (None, "population")
    comp = suggest(prof, "composition", df)
    assert all(p.y is None for p in comp)  # house values are not a total, so shares use counts
    assert _draws(df, panels, tmp_path) == []


def test_wine_aliases_index_column_and_count_rankings(tmp_path):
    n = 3000
    tasters = [f"Taster {i}" for i in range(12)]
    taster = rng.choice(tasters, n)
    handle = np.array([f"@t{tasters.index(t)}" for t in taster], dtype=object)
    handle[taster == "Taster 3"] = "@shared"
    handle[taster == "Taster 4"] = "@shared"  # two people share one handle in the real data
    df = pd.DataFrame({"Unnamed: 0": range(n), "country": rng.choice(["US", "France", "Italy"], n),
                       "description": [f"Ripe {f} fruit, firm tannins and a long, {t} finish with notes of {w}." for f, t, w in
                                       zip(rng.choice(["black", "red", "stone"], n), rng.choice(["spicy", "dry", "soft"], n),
                                           rng.choice(["cedar", "vanilla", "plum", "smoke"], n))],
                       "price": rng.lognormal(3.3, 0.7, n), "points": rng.integers(80, 101, n),
                       "taster_name": taster, "taster_twitter_handle": handle,
                       # a few varieties are very common and most are rare, as in the real data
                       "variety": rng.choice([f"Variety {i}" for i in range(60)], n, p=(w := 1 / np.arange(1, 61)) / w.sum())})
    prof = profile(df)
    assert any(s.action == "drop_columns" and s.columns == ["Unnamed: 0"] and s.safe for s in suggest_cleaning(prof))
    panels = suggest(prof, "comparison", df, limit=20)
    assert not any(p.x == "taster_twitter_handle" for p in panels)
    ranked = [p for p in suggest(prof, "ranking", df, limit=20) if p.x == "variety" and p.chart == "bar_chart"]
    assert ranked and ranked[0].y is None  # count, not mean price over tiny groups
    words = [p for p in suggest(prof, "explore", df, limit=20) if p.chart in ("word_frequency_bar", "word_cloud")]
    assert words and words[0].x == "description"
    assert _draws(df, panels[:8], tmp_path) == []


def test_year_lines_run_in_order():
    from vizdesk.charts.base import _time_series
    from vizdesk.spec import PanelSpec

    df = pd.DataFrame({"release_year": [2020, 1995, 2010, 1995, 2020, 2001], "type": ["Movie", "TV", "Movie", "Movie", "TV", "TV"]})
    assert list(_time_series(df, PanelSpec("line_graph", x="release_year"), by_hue=False).index) == [1995, 2001, 2010, 2020]
    wide = _time_series(df, PanelSpec("line_graph", x="release_year", hue="type"), by_hue=True)
    assert list(wide.index) == [1995, 2001, 2010, 2020]


def test_macos_archive_junk_is_skipped(tmp_path):
    (tmp_path / "__MACOSX" / "data").mkdir(parents=True)
    (tmp_path / "__MACOSX" / "data" / "._a.csv").write_bytes(b"\x00\x05\x16\x07")
    (tmp_path / "._b.csv").write_bytes(b"\x00\x05\x16\x07")
    (tmp_path / "~$book.xlsx").write_bytes(b"lock")
    (tmp_path / "real.csv").write_text("a,b\n1,2\n")
    assert [p.name for p in find_data_files(tmp_path)] == ["real.csv"]


def test_profiling_long_text_is_fast():
    n = 100_000
    df = pd.DataFrame({"review": [f"Bright acidity and red cherry, with a long finish of spice and cedar ({i})." for i in range(n)],
                       "title": [f"Winery {i % 9000} 2014 Reserve" for i in range(n)]})
    start = time.perf_counter()
    profile(df)
    assert time.perf_counter() - start < 5  # was about a minute before dates were sniffed on a sample


KAGGLE = ROOT / "datasets" / "kaggle"


@pytest.mark.skipif(not KAGGLE.is_dir(), reason="real Kaggle files not downloaded (see datasets/)")
@pytest.mark.parametrize("name", sorted(p.name for p in KAGGLE.iterdir()) if KAGGLE.is_dir() else [])
def test_real_kaggle_datasets(name, tmp_path):
    from vizdesk.pipeline import Layout, auto_run

    results = auto_run(KAGGLE / name, "explore", tmp_path, Layout(rows=2, cols=4, width=16, height=8, dpi=40), count=8)
    assert results and all(r.warnings == [] for r in results), [w for r in results for w in r.warnings]
