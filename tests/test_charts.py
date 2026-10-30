"""Every chart in the catalog can be drawn, with data shaped the way its roles ask for."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vizdesk import catalog
from vizdesk.render import REGISTRY, render_figure, validate_panel
from vizdesk.spec import FigureSpec, PanelSpec

N = 240


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return make_frame()


def make_frame() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    t = pd.date_range("2024-01-01", periods=N, freq="D")
    close = 100 + np.cumsum(rng.normal(0, 2, N))
    steps = ["Start", "Check", "Approve", "Reject", "Ship", "Done"]
    src = rng.choice(steps[:4], N)
    nxt = {"Start": "Check", "Check": rng.choice(["Approve", "Reject"]), "Approve": "Ship", "Reject": "Done"}
    return pd.DataFrame({
        "t": t, "end": t + pd.to_timedelta(rng.integers(1, 20, N), unit="D"),
        "a": rng.normal(50, 12, N).round(1), "b": rng.normal(20, 4, N), "c": rng.uniform(1, 9, N),
        "Open": close + rng.normal(0, 1, N), "High": close + 3, "Low": close - 3, "Close": close, "price": close,
        "g": rng.choice(list("ABCD"), N), "h": rng.choice(["X", "Y", "Z"], N), "k": rng.choice(["p", "q"], N),
        "src": src, "dst": [nxt[s] for s in src],
        "lon": rng.uniform(140, 150, N), "lat": rng.uniform(-38, -30, N),
        "lon2": rng.uniform(140, 150, N), "lat2": rng.uniform(-38, -30, N),
        "region": rng.choice(["north", "south"], N),
        "text": rng.choice(["fast delivery great price", "slow delivery helpful support", "great screen quality",
                            "battery life excellent value"], N),
    })


@pytest.fixture(scope="module")
def geojson(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("geo") / "regions.geojson"
    square = lambda x0, y0: [[[x0, y0], [x0 + 5, y0], [x0 + 5, y0 + 4], [x0, y0 + 4], [x0, y0]]]  # noqa: E731
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "North"}, "geometry": {"type": "Polygon", "coordinates": square(140, -34)}},
        {"type": "Feature", "properties": {"name": "South"}, "geometry": {"type": "MultiPolygon", "coordinates": [square(145, -38)]}},
    ]}))
    return str(path)


def panel_for(key: str, geojson: str) -> PanelSpec:
    r = REGISTRY[key]
    special = {
        "line_graph": dict(x="t", y="a", hue="g"), "area_graph": dict(x="t", y="a"),
        "stacked_area_graph": dict(x="t", y="a", hue="g"), "stream_graph": dict(x="t", y="a", hue="g"),
        "calendar": dict(x="t", y="a"), "spiral_plot": dict(x="t", y="a"), "timeline": dict(x="t", hue="g"),
        "timetable": dict(x="t", hue="g", columns=["h"]),
        "candlestick_chart": dict(x="t"), "open_high_low_close_chart": dict(x="t"),
        "kagi_chart": dict(x="t", y="price", options={"reversal": "2%"}), "point_figure_chart": dict(x="t", y="price"),
        "gantt_chart": dict(x="g", columns=["t", "end"]), "illustration_diagram": dict(x="t", y="a"),
        "word_frequency_bar": dict(x="text"), "word_cloud": dict(x="text"),
        "network_diagram": dict(x="src", hue="dst"), "arc_diagram": dict(x="src", hue="dst", size="c"),
        "chord_diagram": dict(x="g", hue="h"), "flow_chart": dict(x="src", hue="dst"),
        "sankey_diagram": dict(columns=["g", "h", "k"], y="c"), "parallel_sets": dict(columns=["g", "h", "k"]),
        "sunburst_diagram": dict(columns=["g", "h", "k"]), "tree_diagram": dict(columns=["g", "h"], y="a"),
        "circle_packing": dict(columns=["g", "h"], y="a"), "brainstorm": dict(columns=["g", "h"]),
        "dot_map": dict(x="lon", y="lat", hue="g"), "bubble_map": dict(x="lon", y="lat", size="c"),
        "choropleth_map": dict(x="region", y="a", options={"geojson": geojson}),
        "connection_map": dict(columns=["lon", "lat", "lon2", "lat2"]),
        "flow_map": dict(columns=["lon", "lat", "lon2", "lat2"], size="c", options={"geojson": geojson}),
        "bullet_graph": dict(x="g", y="a", size="b"), "dumbbell_chart": dict(x="g", columns=["a", "b"]),
        "stem_leaf_plot": dict(x="a"), "histogram": dict(x="a", hue="g"), "density_plot": dict(x="a", hue="g"),
        "ecdf_plot": dict(x="a", hue="g"), "qq_plot": dict(x="a"),
        "heatmap": dict(x="g", hue="h", y="a"), "marimekko_chart": dict(x="g", hue="h", y="a"),
    }
    if key in special:
        return PanelSpec(key, **special[key])
    fields = {"x": "g", "y": "a", "hue": "h", "columns": ["a", "b", "c"]} if r.roles.get("x", ("",))[0] == "cat" else \
             {"x": "a", "y": "b", "hue": "g", "size": "c", "columns": ["a", "b", "c"]}
    return PanelSpec(key, **{k: v for k, v in fields.items() if k in r.roles})


def test_every_catalog_chart_has_a_renderer():
    missing = [c.key for c in catalog.all_charts() if c.key not in REGISTRY]
    assert missing == []


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_chart_draws(key, frame, geojson, tmp_path):
    panel = panel_for(key, geojson)
    assert validate_panel(frame, panel) == []
    spec = FigureSpec(source="memory", panels=[panel], dpi=50, output=str(tmp_path / f"{key}.png"))
    result = render_figure(frame, spec)
    assert result.warnings == []
    assert result.path.stat().st_size > 2000


def test_missing_columns_explain_themselves(frame):
    assert "two or more" in " ".join(validate_panel(frame, PanelSpec("sankey_diagram", columns=["g"])))
    assert validate_panel(frame, PanelSpec("choropleth_map", x="region"))  # no geojson, no lon/lat
    assert "filter" not in " ".join(validate_panel(frame, PanelSpec("bar_chart", x="g")))


def test_filter_option(frame, tmp_path):
    spec = FigureSpec(source="memory", dpi=50, output=str(tmp_path / "f.png"),
                      panels=[PanelSpec("bar_chart", x="g", options={"filter": "h=X|Y"}),
                              PanelSpec("bar_chart", x="g", options={"filter": "h=nope"})], cols=2)
    r = render_figure(frame, spec)
    assert len(r.warnings) == 1 and "no rows left" in r.warnings[0]


def gallery(frame, geojson, out: Path) -> Path:
    """All charts on one sheet, for eyeballing (not run by pytest)."""
    keys = sorted(REGISTRY)
    spec = FigureSpec(source="memory", panels=[panel_for(k, geojson) for k in keys], rows=11, cols=6,
                      width=36, height=60, dpi=45, output=str(out))
    return render_figure(frame, spec).path
