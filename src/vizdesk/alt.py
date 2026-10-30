"""Alt text for figures, written by rules from the same data the chart shows.

Each panel gets one or two sentences: what the chart is, what it plots, and
the main fact a sighted reader would take away (the biggest category, the
direction of a trend, the strength of a correlation ...). No LLM is used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from vizdesk import catalog
from vizdesk.charts.base import _agg_name, _aggregate, _fmt, _num, _value_label, apply_filter
from vizdesk.spec import FigureSpec, PanelSpec

BAR_LIKE = {"bar_chart", "dot_plot", "lollipop_chart", "pie_chart", "donut_chart", "treemap", "pictogram_chart",
            "radial_bar_chart", "radial_column_chart", "tally_chart", "bullet_graph", "error_bars", "word_frequency_bar"}
SPREAD = {"histogram", "density_plot", "ecdf_plot", "qq_plot", "stem_leaf_plot"}
GROUP_SPREAD = {"box_whisker_plot", "violin_plot", "span_chart"}
PAIRS = {"scatterplot", "hexbin_plot", "bubble_chart"}
TIME = {"line_graph", "area_graph", "stacked_area_graph", "stream_graph", "calendar", "spiral_plot", "illustration_diagram",
        "candlestick_chart", "open_high_low_close_chart", "kagi_chart", "point_figure_chart"}
TWO_CATS = {"multi_set_bar_chart", "stacked_bar_graph", "stacked_bar_100", "heatmap", "marimekko_chart"}


def _name(key: str) -> str:
    try:
        return catalog.get(key).name
    except KeyError:
        return key.replace("_", " ")


def _share_sentence(values: pd.Series, what: str) -> str:
    values = values.dropna().sort_values(ascending=False)
    if values.empty:
        return ""
    total = values.clip(lower=0).sum()
    top, bottom = values.index[0], values.index[-1]
    share = f" ({values.iloc[0] / total:.0%} of the total)" if total > 0 and len(values) > 1 else ""
    text = f"{top} is highest at {_fmt(values.iloc[0])}{share}"
    if len(values) > 1:
        text += f"; {bottom} is lowest at {_fmt(values.iloc[-1])}"
    return f"{text}, across {len(values)} {what}."


def _time_facts(df: pd.DataFrame, p: PanelSpec) -> str:
    y = p.y or (_ohlc_close(df) if p.chart in ("candlestick_chart", "open_high_low_close_chart") else None)
    data = df.assign(_t=pd.to_datetime(df[p.x], errors="coerce", format="mixed")).dropna(subset=["_t"])
    if data.empty:
        return ""
    series = (data.assign(_v=_num(data, y)).groupby(data["_t"].dt.to_period("M"))["_v"].agg("sum" if _agg_name(p) == "sum" else "mean")
              if y else data.groupby(data["_t"].dt.to_period("M")).size()).dropna()
    if len(series) < 2:
        return ""
    first, last = series.iloc[0], series.iloc[-1]
    change = f" ({(last - first) / abs(first):+.0%})" if first else ""
    direction = "rises" if last > first else "falls" if last < first else "ends where it started"
    label = y or "the number of rows"
    return (f"From {series.index[0]} to {series.index[-1]}, monthly {label} {direction} from {_fmt(first)} to "
            f"{_fmt(last)}{change}, peaking in {series.idxmax()} at {_fmt(series.max())}.")


def _ohlc_close(df: pd.DataFrame) -> str | None:
    return next((c for c in df.columns if c.lower() == "close"), None)


def describe_panel(df: pd.DataFrame, p: PanelSpec) -> str:
    """One or two plain sentences describing a panel."""
    name = _name(p.chart)
    cols = [c for c in (p.x, p.y, p.hue, p.size) if c] + list(p.columns)
    head = f"{name} of {', '.join(dict.fromkeys(cols))}" if cols else name
    if p.options.get("filter"):
        head += f" (only rows where {p.options['filter']})"
    try:
        df = apply_filter(df, p)
        fact = _fact(df, p)
    except Exception:  # alt text must never break a render
        fact = ""
    return f"{head}. {fact}".strip()


def _fact(df: pd.DataFrame, p: PanelSpec) -> str:
    k = p.chart
    if k == "word_frequency_bar" or k == "word_cloud":
        from vizdesk.charts.specialist import _word_counts

        words = [w for w, _ in _word_counts(df, p.x).most_common(5)]
        return f"The most common words are {', '.join(words)}." if words else ""
    if k in BAR_LIKE and p.x:
        return _share_sentence(_aggregate(df, p.x, p), f"values of {p.x}") if k != "error_bars" else \
            _share_sentence(df.assign(_v=_num(df, p.y)).groupby(p.x, observed=True)["_v"].mean(), f"values of {p.x} (means)")
    if k in SPREAD and p.x:
        v = _num(df, p.x).dropna()
        if v.empty:
            return ""
        skew = v.skew()
        shape = "right-skewed (a long tail of high values)" if skew > 1 else "left-skewed" if skew < -1 else "roughly symmetric"
        return (f"Values run from {_fmt(v.min())} to {_fmt(v.max())} with a median of {_fmt(v.median())}; "
                f"the distribution is {shape}.")
    if k in GROUP_SPREAD and p.y:
        if not p.x:
            v = _num(df, p.y).dropna()
            return f"Median {_fmt(v.median())}, middle half between {_fmt(v.quantile(0.25))} and {_fmt(v.quantile(0.75))}."
        med = df.assign(_v=_num(df, p.y)).groupby(p.x, observed=True)["_v"].median().dropna().sort_values()
        return (f"{med.index[-1]} has the highest median {p.y} ({_fmt(med.iloc[-1])}) and {med.index[0]} the lowest "
                f"({_fmt(med.iloc[0])}).") if len(med) > 1 else ""
    if k in PAIRS and p.x and p.y:
        pair = pd.DataFrame({"x": _num(df, p.x), "y": _num(df, p.y)}).dropna()
        if len(pair) < 3:
            return ""
        r = pair["x"].corr(pair["y"])
        strength = "strongly" if abs(r) >= 0.6 else "moderately" if abs(r) >= 0.3 else "weakly"
        direction = "rises" if r > 0 else "falls"
        return f"{p.y} {strength} {direction} with {p.x} (r = {r:.2f}, {len(pair):,} points)."
    if k == "correlation_heatmap" and len(p.columns) >= 2:
        corr = df[p.columns].apply(pd.to_numeric, errors="coerce").corr()
        np.fill_diagonal(corr.values, np.nan)
        stacked = corr.abs().stack()
        if stacked.empty:
            return ""
        a, b = stacked.idxmax()
        return f"The strongest pair is {a} and {b} (r = {corr.at[a, b]:.2f})."
    if k in TIME and p.x:
        return _time_facts(df, p)
    if k in TWO_CATS and p.x and p.hue:
        wide = _aggregate(df, [p.x, p.hue], p).unstack(p.hue).fillna(0)
        cell = wide.stack().idxmax()
        return f"The largest combination is {p.x} = {cell[0]} with {p.hue} = {cell[1]} ({_fmt(wide.loc[cell])})."
    if k == "missing_values_map":
        gaps = (df.isna().mean() * 100).sort_values(ascending=False)
        gaps = gaps[gaps > 0]
        if gaps.empty:
            return "No values are missing."
        return "Most gaps are in " + ", ".join(f"{c} ({v:.0f}%)" for c, v in gaps.head(3).items()) + "."
    if p.columns and k in ("sankey_diagram", "parallel_sets", "sunburst_diagram", "tree_diagram", "circle_packing", "brainstorm", "treemap"):
        top = _aggregate(df, p.columns[0], p).sort_values(ascending=False)
        return f"The largest {p.columns[0]} is {top.index[0]} ({_fmt(top.iloc[0])} {_value_label(p)})." if len(top) else ""
    if k in ("network_diagram", "arc_diagram", "chord_diagram", "flow_chart") and p.x and p.hue:
        pairs = df.groupby([p.x, p.hue]).size().sort_values(ascending=False)
        return f"{df[p.x].nunique()} sources and {df[p.hue].nunique()} targets; the busiest link is {pairs.index[0][0]} → {pairs.index[0][1]}." if len(pairs) else ""
    if k in ("dot_map", "bubble_map") and p.x and p.y:
        return f"{len(df):,} locations between longitude {_fmt(_num(df, p.x).min())} and {_fmt(_num(df, p.x).max())}."
    return ""


def describe_figure(df: pd.DataFrame, spec: FigureSpec) -> str:
    panels = spec.panels[: spec.rows * spec.cols]
    lines = [f"{spec.title + ': ' if spec.title else ''}Figure with {len(panels)} chart{'s' if len(panels) != 1 else ''} "
             f"in a {spec.rows} by {spec.cols} grid."]
    for i, p in enumerate(panels, 1):
        lines.append(f"{i}. {describe_panel(df, p)}")
    return "\n".join(lines)
