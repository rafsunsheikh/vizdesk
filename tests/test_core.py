"""Profiling, cleaning, suggestions, catalog and rendering."""

import json

import pandas as pd
import pytest

from vizdesk import catalog
from vizdesk.cleaning import apply_steps, suggest_cleaning
from vizdesk.data import load_table, profile
from vizdesk.pipeline import Layout, auto_run, scan, scan_all
from vizdesk.render import REGISTRY, render_figure, render_spec, validate_panel
from vizdesk.spec import FigureSpec, PanelSpec, load_spec
from vizdesk.suggest import GOAL_KEYS


def test_catalog_has_handbook_charts_and_details():
    charts = catalog.all_charts()
    assert len(charts) >= 60
    hist = catalog.get("histogram")
    assert hist.renderable and "distribution" in hist.purposes and hist.use_when
    assert all(c.renderable for c in charts)
    assert {c.key for c in catalog.search("part whole")} >= {"pie_chart"} or catalog.search("composition")
    assert all(c.renderable for c in catalog.search(renderable_only=True))


def test_every_renderer_key_is_in_the_catalog():
    keys = {c.key for c in catalog.all_charts()}
    assert set(REGISTRY) <= keys


def test_profile_detects_kinds(sales_csv):
    p = profile(load_table(sales_csv))
    kinds = {c.name: c.kind for c in p.columns}
    assert kinds["order_id"] == "identifier"
    assert kinds["order_date"] == "datetime" and p.get("order_date").datetime_like
    assert kinds["unit_price"] == "numeric" and p.get("unit_price").numeric_like
    assert kinds["region"] == "categorical"
    assert kinds["country"] == "constant"
    assert p.get("channel").has_padding and p.get("channel").case_variants == 1
    assert p.duplicate_rows == 8


def test_cleaning_suggestions_and_apply(sales_csv):
    df = load_table(sales_csv)
    steps = suggest_cleaning(profile(df))
    actions = {(s.action, tuple(s.columns)) for s in steps}
    assert ("to_numeric", ("unit_price",)) in actions
    assert ("to_datetime", ("order_date",)) in actions
    assert ("drop_duplicates", ()) in actions
    assert any(s.action == "log_transform" and s.columns == ["revenue"] for s in steps)
    safe = [s for s in steps if s.safe]
    assert {s.action for s in safe} <= {"to_numeric", "to_datetime", "strip_whitespace", "drop_columns"}
    out = apply_steps(df, steps)
    assert pd.api.types.is_numeric_dtype(out["unit_price"])
    assert out.duplicated().sum() == 0
    assert set(out["channel"].dropna().unique()) == {"online", "store"}
    assert "revenue_log" in out and "country" not in out
    assert out["discount_pct"].isna().sum() == 0


def test_raw_file_is_never_modified(sales_csv):
    before = sales_csv.read_bytes()
    s = scan(sales_csv, apply_safe=True)
    s.apply(s.cleaning)
    assert sales_csv.read_bytes() == before


@pytest.mark.parametrize("goal", GOAL_KEYS)
def test_suggestions_draw_without_errors(sales_csv, tmp_path, goal):
    s = scan(sales_csv, apply_safe=True)
    panels = s.suggestions(goal, limit=8)
    assert panels, f"no suggestions for {goal}"
    for p in panels:
        assert p.reason and p.chart in REGISTRY
        assert validate_panel(s.data, p) == []
    spec = FigureSpec(source=str(sales_csv), cleaning=s.applied, panels=panels, rows=2, cols=4, width=16, height=8,
                      dpi=60, output=str(tmp_path / f"{goal}.png"))
    r = render_figure(s.data, spec)
    assert r.path.is_file() and r.warnings == []


def test_goal_changes_suggestions(sales_csv):
    s = scan(sales_csv, apply_safe=True)
    trend = {p.chart for p in s.suggestions("trend")}
    comp = {p.chart for p in s.suggestions("composition")}
    assert "line_graph" in trend and "line_graph" not in comp
    assert comp & {"pie_chart", "donut_chart", "treemap", "stacked_bar_100"}


def test_excel_sheets_and_ohlc(data_dir):
    scans = scan_all(data_dir / "markets.xlsx", apply_safe=True)
    assert [s.sheet for s in scans] == ["prices", "sites"]
    prices, sites = scans
    assert prices.suggestions("trend")[0].chart == "candlestick_chart"
    assert any(p.chart == "dot_map" for p in sites.suggestions("explore", limit=20))


def test_layout_padding_and_grid_growth(sales_csv, tmp_path):
    s = scan(sales_csv, apply_safe=True)
    panels = [PanelSpec("histogram", x="revenue")] * 5
    spec = FigureSpec(source=str(sales_csv), panels=list(panels), rows=1, cols=2, width=6, height=3, dpi=50,
                      padding=False, output=str(tmp_path / "grow.png"))
    render_figure(s.data, spec)
    assert (spec.rows, spec.cols) == (2, 3)
    assert load_spec(tmp_path / "grow.png").padding is False


def test_bad_panel_is_reported_not_fatal(sales_csv, tmp_path):
    s = scan(sales_csv, apply_safe=True)
    spec = FigureSpec(source=str(sales_csv), panels=[PanelSpec("histogram", x="revenue"), PanelSpec("scatterplot", x="nope")],
                      rows=1, cols=2, dpi=50, output=str(tmp_path / "bad.png"))
    r = render_figure(s.data, spec)
    assert r.path.is_file() and len(r.warnings) == 1 and "nope" in r.warnings[0]


def test_recipe_round_trip_and_redraw(sales_csv, tmp_path):
    s = scan(sales_csv, apply_safe=True)
    out = tmp_path / "fig.png"
    spec = FigureSpec(source=str(sales_csv), cleaning=s.applied, panels=[PanelSpec("bar_chart", x="region", y="revenue")],
                      dpi=50, output=str(out))
    render_figure(s.data, spec)
    saved = json.loads((tmp_path / "fig.vizdesk.json").read_text())
    assert saved["panels"][0]["chart"] == "bar_chart" and saved["cleaning"]
    again = load_spec(out)
    again.panels[0].chart = "dot_plot"
    again.cols = 2
    again.panels.append(PanelSpec("histogram", x="unit_price"))  # needs the recorded to_numeric cleaning
    r = render_spec(again)
    assert r.warnings == []
    assert load_spec(out).panels[0].chart == "dot_plot"


def test_auto_run_paginates(data_dir, tmp_path):
    results = auto_run(data_dir / "sales.csv", "explore", tmp_path, Layout(rows=1, cols=3, width=9, height=3, dpi=40), count=7)
    assert [r.path.name for r in results] == [f"sales-explore-0{i}.png" for i in (1, 2, 3)]
    assert all(r.spec_path.is_file() for r in results)
