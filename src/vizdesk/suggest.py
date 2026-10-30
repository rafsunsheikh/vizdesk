"""Rule-based chart suggestions. No LLM: every suggestion comes from the column
profile, a few statistics computed on the data, and the goal the user picked.
Each one carries a plain-language reason with the numbers behind it.

The rules follow what popular Kaggle EDA notebooks do: split every category
by the target, histogram every numeric column, rank categories by a total,
draw trends for dates, map coordinates, and so on.

Scores run from 0 to 100. They only rank suggestions against each other;
they are not probabilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd

from vizdesk.data import ColumnProfile, DatasetProfile, numeric_frame
from vizdesk.spec import PanelSpec


@dataclass(frozen=True)
class Goal:
    key: str
    label: str
    question: str


GOALS = [
    Goal("explore", "Explore everything", "I am not sure yet; show me the most useful overview."),
    Goal("target", "Explain a target", "What goes with the target column (churn, survival, price)?"),
    Goal("distribution", "Understand distributions", "How are the values spread out? Are there outliers or skew?"),
    Goal("comparison", "Compare groups", "How do categories or groups differ from each other?"),
    Goal("relationship", "Find relationships", "Which variables move together?"),
    Goal("composition", "Show composition", "What is the whole made of, and what share is each part?"),
    Goal("trend", "Show change over time", "How do the numbers change over time?"),
    Goal("ranking", "Rank items", "Which items are top or bottom?"),
    Goal("data_quality", "Check data quality", "Where are the gaps, errors and outliers?"),
]
GOAL_KEYS = [g.key for g in GOALS]

_SUM_HINT = re.compile(r"(sales|revenue|amount|total|count|qty|quantity|units|spend|volume|profit|orders|visits)", re.I)
_CLASS_TARGET = re.compile(r"(churn|survived|target|label|class|outcome|default|fraud|attrition|response|converted|exited|"
                           r"diagnosis|^y$|^is_|^has_|left)", re.I)
_NUMBER_TARGET = [re.compile(p, re.I) for p in (r"target", r"price", r"value", r"sales", r"revenue", r"profit", r"salary",
                                                r"score", r"points", r"cost")]
_POSITIVE = {"yes", "1", "true", "y", "t", "churned", "survived", "default", "fraud", "positive", "left"}
_SIZE_HINT = re.compile(r"(population|count|volume|size|households|visitors|total)", re.I)
_DERIVED = ("_log", "_z", "_scaled")


@dataclass
class Target:
    column: str
    kind: str  # "class" or "number"
    positive: str | None = None  # the class whose rate is reported, e.g. "Yes" for Churn

    def describe(self) -> str:
        return f"'{self.column}'" + (f" (share of '{self.positive}')" if self.positive else "")

    @property
    def outcome(self) -> str:
        """'Churn = Yes' or 'Survived = 1': the class whose share the charts report."""
        return f"{self.column} = {self.positive}"


@dataclass
class Context:
    prof: DatasetProfile
    df: pd.DataFrame | None
    measures: list[ColumnProfile]
    cats: list[ColumnProfile]  # 2-30 values, most informative first
    many: list[ColumnProfile]  # more than 30 values, or list columns: for top-N rankings
    times: list[ColumnProfile]
    years: list[ColumnProfile]
    target: Target | None
    value: ColumnProfile | None
    stats: dict = field(default_factory=dict)  # column -> association with the target / value
    target_profile: ColumnProfile | None = None

    @property
    def small_cats(self) -> list[ColumnProfile]:
        return [c for c in self.cats if c.unique <= 8]

    @property
    def big(self) -> bool:
        return self.prof.rows > 20000

    def names(self) -> set[str]:
        return {c.name for c in self.prof.columns}


# ---------------------------------------------------------------- building the context


def _derived_from(name: str, names: set[str]) -> bool:
    """'revenue_log' is derived when 'revenue' is also a column (made by a cleaning step)."""
    return any(name.endswith(sfx) and name[: -len(sfx)] in names for sfx in _DERIVED)


def _mixed_units(name: str, names: set[str]) -> bool:
    """'duration_value' next to 'duration_unit' mixes minutes and seasons: only usable with a unit filter."""
    return name.endswith("_value") and f"{name[:-6]}_unit" in names


def _sample(df: pd.DataFrame, n: int = 20000) -> pd.DataFrame:
    return df if len(df) <= n else df.sample(n, random_state=0)


def find_target(prof: DatasetProfile, df: pd.DataFrame | None, name: str | None = None) -> Target | None:
    """The column a notebook would call 'the target': named by the user, or recognised by its name."""
    cols = {c.name: c for c in prof.columns}
    candidates = [cols[name]] if name and name in cols else []
    if not candidates:
        candidates = [c for c in prof.columns if (c.is_category and c.unique <= 5 and _CLASS_TARGET.search(c.name))]
    if not candidates and not _has_ohlc(prof):
        names = {c.name for c in prof.columns}
        usable = [c for c in prof.columns if c.is_measure and not _derived_from(c.name, names) and not _mixed_units(c.name, names)]
        for pattern in _NUMBER_TARGET:
            hit = next((c for c in usable if pattern.search(c.name)), None)
            if hit:
                candidates = [hit]
                break
    if not candidates:
        return None
    c = candidates[0]
    if c.kind == "numeric" and c.unique > 10:
        return Target(c.name, "number")
    positive = None
    if df is not None and c.name in df:
        labels = df[c.name].dropna().astype(str).str.strip()
        counts = labels.value_counts()
        positive = next((v for v in counts.index if v.lower() in _POSITIVE), counts.index[-1] if len(counts) else None)
    return Target(c.name, "class", positive)


def _class_rates(df: pd.DataFrame, col: str, target: Target) -> pd.Series:
    """Share of rows with the positive target class, per value of `col` (groups with < 1% of rows dropped)."""
    hit = df[target.column].astype(str).str.strip() == target.positive
    groups = df[col].astype(str)
    sizes = groups.value_counts()
    keep = sizes[sizes >= max(20, 0.01 * len(df))].index
    return hit.groupby(groups).mean().loc[lambda s: s.index.isin(keep)].sort_values()


def _association(ctx: Context, c: ColumnProfile) -> float:
    """How strongly a column goes with the target (or the main measure). 0 = not at all."""
    df, t = ctx.df, ctx.target
    if df is None or c.name not in df:
        return 0.0
    if t and t.kind == "class":
        if c.is_category or c.kind == "categorical":
            rates = _class_rates(df, c.name, t)
            return float(rates.max() - rates.min()) if len(rates) > 1 else 0.0
        if c.is_measure:  # Cohen's d between the two groups
            hit = df[t.column].astype(str).str.strip() == t.positive
            v = pd.to_numeric(df[c.name], errors="coerce")
            a, b = v[hit].dropna(), v[~hit].dropna()
            sd = np.sqrt((a.var() + b.var()) / 2) if len(a) > 1 and len(b) > 1 else 0
            return float(abs(a.mean() - b.mean()) / sd) if sd else 0.0
    measure = t.column if t else (ctx.value.name if ctx.value else None)
    if not measure or measure == c.name:
        return 0.0
    y = pd.to_numeric(df[measure], errors="coerce")
    if c.is_measure:
        r = pd.to_numeric(df[c.name], errors="coerce").corr(y)
        return float(abs(r)) if pd.notna(r) else 0.0
    if c.is_category:  # eta squared: share of the measure's variance explained by the groups
        total = y.var()
        if not total:
            return 0.0
        means = y.groupby(df[c.name].astype(str)).transform("mean")
        return float(((means - y.mean()) ** 2).mean() / total)
    return 0.0


def _drop_aliases(cats: list[ColumnProfile], df: pd.DataFrame) -> list[ColumnProfile]:
    """Two columns that map one-to-one (a name and its code, a person and their handle) say the same thing:
    keep the one with fewer gaps."""
    dropped: set[str] = set()
    for a, b in combinations(sorted(cats, key=lambda c: c.missing_pct), 2):
        if a.name in dropped or b.name in dropped:
            continue
        pair = df[[a.name, b.name]].dropna()
        if not len(pair):
            continue
        one_way = (pair.groupby(a.name)[b.name].nunique() == 1).mean()
        other_way = (pair.groupby(b.name)[a.name].nunique() == 1).mean()
        if one_way >= 0.9 and other_way >= 0.9:  # real data has exceptions, e.g. two people sharing one handle
            dropped.add(b.name)
    return [c for c in cats if c.name not in dropped]


def build_context(prof: DatasetProfile, df: pd.DataFrame | None, target: str | None = None) -> Context:
    names = {c.name for c in prof.columns}
    measures = [c for c in prof.numeric if c.is_measure and not _derived_from(c.name, names) and not _mixed_units(c.name, names)]
    measures.sort(key=lambda c: (c.missing_pct, not _SUM_HINT.search(c.name), -c.unique))
    cats = [c for c in prof.categorical if 2 <= c.unique <= 30 and not c.multi_valued and not c.units and c.avg_length <= 40
            and not (c.name.endswith("_unit") and f"{c.name[:-5]}_value" in names)]
    many = [c for c in prof.categorical if (c.unique > 30 or c.multi_valued) and not c.units]
    sample = _sample(df) if df is not None else None
    tgt = find_target(prof, sample, target)
    value = None
    if tgt and tgt.kind == "number":
        value = next((c for c in measures if c.name == tgt.column), None)
    if value is None:
        value = next((c for c in measures if _SUM_HINT.search(c.name)), measures[0] if measures else None)
    if sample is not None:
        cats = _drop_aliases(cats, sample)
    ctx = Context(prof, sample, measures, cats, many, prof.datetime, [c for c in prof.numeric if c.is_year], tgt, value)
    for c in cats + measures:
        ctx.stats[c.name] = _association(ctx, c)
    if tgt:
        cats[:] = [c for c in cats if c.name != tgt.column]
        ctx.target_profile = prof.get(tgt.column)
    many.sort(key=lambda c: (c.missing_pct > 30, c.unique > 2000, c.missing_pct))
    if tgt or value:
        cats.sort(key=lambda c: (c.avg_length > 20, c.missing_pct > 30, -ctx.stats.get(c.name, 0)))
        others = [c for c in measures if c.name != (tgt.column if tgt else "") and c.name != (value.name if value else "")]
        measures[:] = ([value] if value else []) + sorted(others, key=lambda c: -ctx.stats.get(c.name, 0))
    else:
        cats.sort(key=lambda c: (c.avg_length > 20, c.missing_pct, abs(c.unique - 6)))
    return ctx


# ---------------------------------------------------------------- small helpers


def _has_ohlc(prof: DatasetProfile) -> bool:
    return len(_ohlc_columns(prof)) == 4


def _ohlc_columns(prof: DatasetProfile) -> list[str]:
    lower = {c.name.lower(): c.name for c in prof.numeric}
    return [lower[k] for k in ("open", "high", "low", "close") if k in lower]


def _latlon(prof: DatasetProfile) -> tuple[str, str] | None:
    names = {c.name.lower(): c.name for c in prof.numeric}
    lon = next((names[k] for k in ("longitude", "lon", "lng", "long") if k in names), None)
    lat = next((names[k] for k in ("latitude", "lat") if k in names), None)
    return (lon, lat) if lon and lat else None


def _entity(ctx: Context) -> tuple[str, list[str]] | None:
    """A column like a stock ticker in price data: many values, each with its own long series.
    Returns the column and its most traded values (highest mean volume), or the ones with most rows."""
    lower = {c.name.lower() for c in ctx.prof.numeric}
    if ctx.df is None or not ctx.times or not (_has_ohlc(ctx.prof) or {"close", "price"} & lower):
        return None
    volume = next((c.name for c in ctx.prof.numeric if "volume" in c.name.lower()), None)
    for c in ctx.prof.categorical:
        if 10 <= c.unique <= 5000 and ctx.prof.rows / c.unique >= 20:
            if volume:
                ranked = pd.to_numeric(ctx.df[volume], errors="coerce").groupby(ctx.df[c.name]).mean().sort_values(ascending=False)
            else:
                ranked = ctx.df[c.name].value_counts()
            return c.name, [str(v) for v in ranked.index[:5]]
    return None


def _nested(ctx: Context) -> list[tuple[str, str]]:
    """(parent, child) pairs where every child value sits under exactly one parent, e.g. Category > Sub-Category."""
    if ctx.df is None:
        return []
    pairs = []
    pool = [c for c in ctx.prof.categorical if 2 <= c.unique <= 200 and not c.multi_valued]
    for a in pool:
        for b in pool:
            if max(4, 1.5 * a.unique) <= b.unique <= a.unique * 25 and a.name != b.name:
                parents = ctx.df.groupby(b.name, observed=True)[a.name].nunique()
                if len(parents) and parents.max() == 1:
                    pairs.append((a.name, b.name))
    return sorted(pairs, key=lambda ab: ctx.prof.get(ab[1]).unique)[:3]


def _name_list(ctx: Context, c: ColumnProfile) -> bool:
    """'Tom Hanks, Meg Ryan, ...': comma-separated names, not sentences."""
    if ctx.df is None:
        return False
    values = ctx.df[c.name].dropna().astype(str)
    if values.str.count(",").mean() < 2:
        return False
    items = values.head(500).str.split(",").explode().str.split().str.len()
    return float(items.mean()) <= 3  # names between the commas; sentences have longer pieces


def _long_tail(c: ColumnProfile | None) -> bool:
    return bool(c and c.min is not None and c.min >= 0 and c.skew is not None and c.skew > 2)


def _log_opts(x: ColumnProfile | None = None, y: ColumnProfile | None = None) -> dict:
    axes = ("x" if _long_tail(x) else "") + ("y" if _long_tail(y) else "")
    return {"log": axes} if axes else {}


def _order(c: ColumnProfile) -> dict:
    return {"order": "label"} if c.ordinal or c.name.endswith("_group") else {}


def _pct(v: float) -> str:
    return f"{v:.0%}"


# ---------------------------------------------------------------- the rules


def suggest(prof: DatasetProfile, goal: str = "explore", df: pd.DataFrame | None = None, limit: int = 12,
            target: str | None = None) -> list[PanelSpec]:
    """Return chart suggestions, best first. With df, ranks by real statistics (correlations, target rates)."""
    if goal not in GOAL_KEYS:
        raise ValueError(f"unknown goal '{goal}'. Choose from: {', '.join(GOAL_KEYS)}")
    ctx = build_context(prof, df, target)
    out: list[tuple[float, PanelSpec]] = []
    want = {goal} if goal != "explore" else set(GOAL_KEYS)

    def add(score: float, panel: PanelSpec) -> None:
        out.append((score, panel))

    families = [
        *([("trend", lambda add: _trend_rules(ctx, add))] if _entity(ctx) else []),  # price series: the trend is the story
        ("target", lambda add: _target_rules(ctx, add) if ctx.target else None),
        ("distribution", lambda add: _distribution_rules(ctx, add)),
        ("comparison", lambda add: _comparison_rules(ctx, add)),
        ("relationship", lambda add: _relationship_rules(ctx, add)),
        ("geo", lambda add: _geo_rules(ctx, add)),
        ("composition", lambda add: _composition_rules(ctx, add)),
        *([] if _entity(ctx) else [("trend", lambda add: _trend_rules(ctx, add))]),
        ("ranking", lambda add: _ranking_rules(ctx, add)),
        ("text", lambda add: _text_rules(ctx, add)),
        ("data_quality", lambda add: _quality_rules(ctx, add)),
    ]
    extra = {"geo": ("distribution", "relationship", "target"), "text": ("distribution", "ranking")}
    groups: list[list[tuple[float, PanelSpec]]] = []
    for name, rules in families:
        if name in want or goal in extra.get(name, ()) or (goal == "explore" and name in extra):
            bucket: list[tuple[float, PanelSpec]] = []
            rules(lambda score, panel, b=bucket: b.append((score, panel)))
            groups.append(sorted(bucket, key=lambda t: -t[0]))
    if goal == "explore":
        return _round_robin(groups, limit, quality=ctx.prof)
    out = [item for g in groups for item in g]
    return _pick(out, goal, limit)


def _round_robin(groups: list[list[tuple[float, PanelSpec]]], limit: int, quality: DatasetProfile) -> list[PanelSpec]:
    """Overview: the best suggestion of each family in turn (two from the target family), then the next best."""
    worst_gap = max((c.missing_pct for c in quality.columns), default=0)
    in_grid = {c for g in groups for _, p in g if p.chart == "histogram_grid" for c in p.columns}

    def useful(item) -> bool:
        panel = item[1]
        if panel.chart == "missing_values_map" and worst_gap < 5:
            return False  # a handful of gaps does not earn a slot in the overview
        return not (panel.chart == "histogram" and panel.x in in_grid and not panel.options.get("filter"))

    queues = [[item for item in g if useful(item)] for g in groups]
    ordered: list[tuple[float, PanelSpec]] = []
    first = True
    while any(queues):
        for i, q in enumerate(queues):
            take = 3 if first and i == 0 else 1  # the target family leads with three charts
            ordered += q[:take]
            del q[:take]
        first = False
    return _pick(ordered, "explore", limit, keep_order=True)


def _target_rules(ctx: Context, add, boost: float = 0) -> None:
    t = ctx.target
    if t.kind == "class":
        add(82 + boost, PanelSpec("donut_chart", x=t.column,
            reason=f"The overall split of {t.describe()}: the baseline every other chart is compared with."))
        ranked = sorted(ctx.cats, key=lambda c: -ctx.stats.get(c.name, 0))
        for i, c in enumerate(ranked[:6]):
            rates = _class_rates(ctx.df, c.name, t) if ctx.df is not None else pd.Series(dtype=float)
            if len(rates) < 2:
                continue
            spread = rates.max() - rates.min()
            add(78 + boost + 15 * spread - i, PanelSpec("stacked_bar_100", x=c.name, hue=t.column, options=_order(c),
                reason=f"The share of rows with {t.outcome} ranges from {_pct(rates.min())} ({c.name} = {rates.index[0]}) "
                       f"to {_pct(rates.max())} ({c.name} = {rates.index[-1]})."))
        nums = sorted((c for c in ctx.measures if c.name != t.column), key=lambda c: -ctx.stats.get(c.name, 0))
        for i, c in enumerate(nums[:3]):
            d = ctx.stats.get(c.name, 0)
            med = ""
            if ctx.df is not None:
                hit = ctx.df[t.column].astype(str).str.strip() == t.positive
                v = pd.to_numeric(ctx.df[c.name], errors="coerce")
                med = f" (median {v[hit].median():.4g} when {t.column} = {t.positive}, {v[~hit].median():.4g} otherwise)"
            add(76 + boost + 6 * min(d, 1.5) - i, PanelSpec("box_whisker_plot", y=c.name, x=t.column,
                reason=f"Does '{c.name}' differ by {t.column}?{med} Effect size d = {d:.2f}."))
            if i == 0:
                add(70 + boost, PanelSpec("density_plot", x=c.name, hue=t.column,
                    reason=f"The two {t.column} groups' '{c.name}' curves overlaid; the gap shows how well it separates them."))
    else:
        has_log = f"{t.column}_log" in ctx.names()
        add(80 + boost, PanelSpec("histogram", x=f"{t.column}_log" if has_log else t.column,
            options={} if has_log else _log_opts(ctx.target_profile),
            reason=f"The distribution of the target '{t.column}'" + (" on a log scale (long tail)." if _long_tail(ctx.target_profile) and not has_log else ".")))
        nums = sorted((c for c in ctx.measures if c.name != t.column), key=lambda c: -ctx.stats.get(c.name, 0))
        for i, c in enumerate(nums[:3]):
            r = ctx.stats.get(c.name, 0)
            add(76 + boost + 15 * r - i, PanelSpec("hexbin_plot" if ctx.big else "scatterplot", x=c.name, y=t.column,
                options=_log_opts(c, ctx.target_profile),
                reason=f"'{c.name}' is the {['strongest', 'second strongest', 'third strongest'][i]} straight-line "
                       f"partner of '{t.column}' (|r| = {r:.2f})."))
        for i, c in enumerate(sorted(ctx.cats, key=lambda c: -ctx.stats.get(c.name, 0))[:2]):
            add(74 + boost + 20 * ctx.stats.get(c.name, 0) - i, PanelSpec("box_whisker_plot", y=t.column, x=c.name, options=_order(c),
                reason=f"How '{t.column}' differs across '{c.name}' (explains {ctx.stats.get(c.name, 0):.0%} of its variance)."))


def _distribution_rules(ctx: Context, add) -> None:
    names = ctx.names()
    if len(ctx.measures) >= 3:
        cols = [f"{c.name}_log" if f"{c.name}_log" in names else c.name for c in ctx.measures[:12]]
        capped = [c.name for c in ctx.measures if c.capped_pct]
        add(86, PanelSpec("histogram_grid", columns=cols,
            reason=f"The shape of all {len(cols)} numeric columns at once, the first look most notebooks take"
                   + (f"; watch the spikes at the maximum in {', '.join(capped)} (capped values)." if capped else ".")))
    for i, c in enumerate(ctx.measures[:4]):
        if f"{c.name}_log" in names:
            add(84 - i, PanelSpec("histogram", x=f"{c.name}_log",
                reason=f"Uses the log of '{c.name}' (from the cleaning step), so its long tail no longer squashes the chart."))
            continue
        skewed = c.skew is not None and abs(c.skew) > 1
        add(80 - i + (4 if skewed else 0), PanelSpec("histogram", x=c.name, options=_log_opts(c),
            reason=f"Where values of '{c.name}' bunch up" + (f", and its {'right' if c.skew > 0 else 'left'} skew ({c.skew:.1f})"
                                                          if skewed else "")
                   + ("; drawn on a log scale so the long tail does not hide the rest." if _long_tail(c) else ".")))
    group = ctx.small_cats[0] if ctx.small_cats else None
    for i, c in enumerate(ctx.measures[:2]):
        if group:
            add(74 - i, PanelSpec("box_whisker_plot", y=c.name, x=group.name, options=_order(group),
                reason=f"Spread of '{c.name}' in each of the {group.unique} groups of '{group.name}'."))
            add(64 - i, PanelSpec("violin_plot", y=c.name, x=group.name, options=_order(group),
                reason=f"Like the box plot, but also shows if '{c.name}' has two or more peaks within a group."))
    smooth = [c for c in ctx.measures if not _long_tail(c)]
    if smooth:
        c = smooth[0]
        hue = ctx.target.column if ctx.target and ctx.target.kind == "class" else (group.name if group and group.unique <= 5 else None)
        add(68, PanelSpec("density_plot", x=c.name, hue=hue, reason=f"A smooth curve of '{c.name}' that does not depend on bin width."))
        add(58, PanelSpec("ecdf_plot", x=c.name, reason=f"Read off percentiles directly, e.g. what share of rows have '{c.name}' below a value."))
        add(50, PanelSpec("qq_plot", x=c.name, reason=f"Checks whether '{c.name}' is close to a normal distribution."))
    for c in ctx.cats[:3]:
        if c.ordinal:
            add(66, PanelSpec("bar_chart", x=c.name, options=_order(c), reason=f"Count of each value of '{c.name}', in order."))
    for col in [c for c in ctx.prof.columns if c.units]:
        unit_col, value_col = f"{col.name}_unit", f"{col.name}_value"
        if value_col in names:
            for u in col.units[:3]:
                add(72, PanelSpec("histogram", x=value_col, options={"filter": f"{unit_col}={u}"},
                    title=f"{col.name} in {u}s", reason=f"'{col.name}' mixes units; this shows only the rows measured in {u}s."))


def _comparison_rules(ctx: Context, add) -> None:
    v = ctx.value
    for i, g in enumerate(ctx.cats[:3]):
        if v and g.name != v.name:
            eta = ctx.stats.get(g.name, 0)
            add(82 - 3 * i + 10 * eta, PanelSpec("bar_chart", x=g.name, y=v.name, options=_order(g),
                reason=f"Compares '{v.name}' across the {g.unique} values of '{g.name}'"
                       + (f"; the groups explain {eta:.0%} of its variance." if eta else ".")))
        add(72 - 3 * i, PanelSpec("bar_chart", x=g.name, options=_order(g), reason=f"How many rows fall in each '{g.name}'."))
    if v and ctx.cats:
        g = ctx.cats[0]
        add(66, PanelSpec("error_bars", x=g.name, y=v.name,
            reason=f"Average '{v.name}' per '{g.name}' with ± 1 standard deviation: are the differences bigger than the noise?"))
        h = next((c for c in ctx.cats[1:] if c.unique <= 6), None)
        if h:
            add(70, PanelSpec("multi_set_bar_chart", x=g.name, hue=h.name, y=v.name, options=_order(g),
                reason=f"Compares '{h.name}' side by side within each '{g.name}'."))
    if len(ctx.measures) >= 3 and ctx.small_cats:
        group = ctx.small_cats[0].name
        add(56, PanelSpec("radar_chart", columns=[c.name for c in ctx.measures[:6]], x=group,
            reason="Profiles several numeric columns at once (each scaled 0-1), one shape per group."))
    for c in ctx.many[:2]:
        if (bar := _top_bar(ctx, c)) is not None:
            add(68, bar)


def _top_bar(ctx: Context, c: ColumnProfile) -> PanelSpec | None:
    options = {"split": c.name} if c.multi_valued else {}
    y = _additive(ctx) if not c.multi_valued else None  # rank by a total or by count: an average over tiny groups misleads
    what = f"total {y}" if y else "count of rows"
    reason = (f"'{c.name}' holds lists ({c.item_unique} distinct items); each item is counted once per row it appears in."
              if c.multi_valued else f"The top 15 of the {c.unique} values of '{c.name}' by {what}.")
    if ctx.df is not None and not y and not c.multi_valued:
        counts = ctx.df[c.name].value_counts()
        if len(counts) > 1 and counts.std() / counts.mean() < 0.3:
            return None  # every value has about the same number of rows (a random sample adds ~0.15 of noise)
    return PanelSpec("bar_chart", x=c.name, y=y, top_n=15, options=options, title=f"Top 15 {c.name}", reason=reason)


def _relationship_rules(ctx: Context, add) -> None:
    nums = ctx.measures[:12]
    if _entity(ctx):
        return  # pooling hundreds of separate series into one scatter mixes unrelated things
    if len(nums) >= 2 and ctx.df is not None:
        names = [c.name for c in nums]
        corr = numeric_frame(ctx.df, names).corr()
        pairs = sorted(((a, b, float(corr.at[a, b])) for a, b in combinations(names, 2) if pd.notna(corr.at[a, b])),
                       key=lambda t: -abs(t[2]))
        shown = 0
        for a, b, r in pairs:
            if abs(r) > 0.95:  # open vs close, rooms vs bedrooms: nearly the same thing twice
                continue
            strength = "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.3 else "weak"
            hue = (ctx.target.column if ctx.target and ctx.target.kind == "class" else
                   ctx.small_cats[0].name if ctx.small_cats else None)
            add(70 + 20 * abs(r) - shown, PanelSpec("hexbin_plot" if ctx.big else "scatterplot", x=a, y=b,
                hue=None if ctx.big else hue, options=_log_opts(ctx.prof.get(a), ctx.prof.get(b)),
                reason=f"'{a}' and '{b}' have a {strength} correlation (r = {r:.2f})."
                       + (" Hexbin is used because there are many rows." if ctx.big else "")))
            shown += 1
            if shown == 3:
                break
    if len(nums) >= 3 and not _has_ohlc(ctx.prof):  # prices of one asset are all ~1.0 correlated
        cols = [c.name for c in nums]
        if ctx.target and ctx.target.kind == "class" and ctx.df is not None and pd.api.types.is_numeric_dtype(ctx.df[ctx.target.column]):
            cols.append(ctx.target.column)
        add(80, PanelSpec("correlation_heatmap", columns=cols, reason=f"One picture of how all {len(cols)} numeric columns relate."))
        add(58, PanelSpec("scatter_matrix", columns=cols[:5], reason="Every pairwise scatterplot at once, with histograms on the diagonal."))
        size = next((c for c in nums[2:] if c.all_positive), None)
        if size:
            add(62, PanelSpec("bubble_chart", x=nums[0].name, y=nums[1].name, size=size.name,
                reason=f"Adds '{size.name}' as bubble area to the '{nums[0].name}' vs '{nums[1].name}' scatter."))
        add(52, PanelSpec("parallel_coordinates_plot", columns=cols[:6], hue=ctx.small_cats[0].name if ctx.small_cats else None,
            reason="Follows each row across several numeric columns; good for spotting clusters."))
    if len(ctx.cats) >= 2:
        a, b = ctx.cats[0], ctx.cats[1]
        add(60, PanelSpec("heatmap", x=a.name, hue=b.name, reason=f"Counts every combination of '{a.name}' and '{b.name}'."))


def _additive(ctx: Context) -> str | None:
    """The measure, if it is a total that can be split into shares (sales, units); else None (use counts).
    A share of an average or a price is meaningless."""
    v = ctx.value
    return v.name if v and v.all_positive and _SUM_HINT.search(v.name) else None


def _composition_rules(ctx: Context, add) -> None:
    positive = _additive(ctx)
    what = f"'{positive}'" if positive else "rows"
    for parent, child in _nested(ctx):
        add(80, PanelSpec("sunburst_diagram", columns=[parent, child], y=positive,
            reason=f"Every '{child}' belongs to one '{parent}', so they form a hierarchy; rings show the share of {what} at each level."))
        add(76, PanelSpec("treemap", x=child, y=positive,
            reason=f"The share of {what} for each of the {ctx.prof.get(child).unique} values of '{child}', in one rectangle."))
    if ctx.cats:
        g = ctx.cats[0]
        if g.unique <= 6:
            add(76, PanelSpec("donut_chart", x=g.name, y=positive, reason=f"'{g.name}' has only {g.unique} values, so shares of {what} read well as slices."))
            add(66, PanelSpec("pie_chart", x=g.name, y=positive, reason=f"Classic share-of-whole view of '{g.name}'."))
        else:
            add(72, PanelSpec("treemap", x=g.name, y=positive, reason=f"Shares of {what} for {g.unique} values of '{g.name}'; scales to many categories."))
        h = next((c for c in ctx.cats if c.name != g.name and c.unique <= 8), None)
        if h:
            add(74, PanelSpec("stacked_bar_100", x=g.name, hue=h.name, y=positive, options=_order(g),
                reason=f"The share of each '{h.name}' inside every '{g.name}'."))
            add(64, PanelSpec("stacked_bar_graph", x=g.name, hue=h.name, y=positive, options=_order(g),
                reason=f"Totals per '{g.name}', split by '{h.name}'."))
    if ctx.times and ctx.small_cats and positive:
        add(66, PanelSpec("stacked_area_graph", x=ctx.times[0].name, hue=ctx.small_cats[0].name, y=positive,
            reason=f"How each '{ctx.small_cats[0].name}' contributes to the total {positive} over time."))


def _trend_rules(ctx: Context, add) -> None:
    names = ctx.names()
    entity = _entity(ctx)
    for t in ctx.times[:1]:
        ohlc = _ohlc_columns(ctx.prof)
        if entity:
            col, top = entity
            close = next((c for c in ohlc[3:]), ctx.value.name if ctx.value else None)
            if len(ohlc) == 4:
                add(92, PanelSpec("candlestick_chart", x=t.name, columns=ohlc, options={"filter": f"{col}={top[0]}", "last": "120"},
                    reason=f"'{col}' holds {ctx.prof.get(col).unique} separate series; this is the last 120 periods of {top[0]}, "
                           f"the most traded. Change the filter to see another."))
            if close:
                add(88, PanelSpec("line_graph", x=t.name, y=close, options={"filter": f"{col}={top[0]}", "rolling": "50"},
                    reason=f"'{close}' of {top[0]} with a 50-period moving average to show the trend under the noise."))
                add(84, PanelSpec("line_graph", x=t.name, y=close, hue=col, options={"filter": f"{col}={'|'.join(top[:4])}"},
                    reason=f"Compares {', '.join(top[:4])}, the four most traded {col} values."))
            volume = next((c.name for c in ctx.measures if "volume" in c.name.lower()), None)
            if volume:
                add(70, PanelSpec("line_graph", x=t.name, y=volume, options={"filter": f"{col}={top[0]}"},
                    reason=f"Trading activity ({volume}) of {top[0]} over time."))
                add(76, PanelSpec("bar_chart", x=col, y=volume, agg="mean", top_n=15, title=f"Most traded {col}",
                    reason=f"The 15 {col} values with the highest average {volume}."))
            continue
        if len(ohlc) == 4:
            add(92, PanelSpec("candlestick_chart", x=t.name, columns=ohlc, reason="Found open, high, low and close columns."))
        add(84 if not ctx.value else 74, PanelSpec("line_graph", x=t.name, reason=f"How many rows there are in each period of '{t.name}'."))
        if ctx.value:
            add(88, PanelSpec("line_graph", x=t.name, y=ctx.value.name,
                reason=f"'{t.name}' is a date column, so a line shows how '{ctx.value.name}' changes over time."))
            for c in ctx.measures[1:3]:
                add(68, PanelSpec("line_graph", x=t.name, y=c.name, reason=f"'{c.name}' over '{t.name}'."))
            add(62, PanelSpec("area_graph", x=t.name, y=ctx.value.name, reason=f"Emphasises the overall volume of '{ctx.value.name}' over time."))
        hue = ctx.small_cats[0] if ctx.small_cats else (ctx.cats[0] if ctx.cats and ctx.cats[0].unique <= 8 else None)
        if hue:
            add(80, PanelSpec("line_graph", x=t.name, y=ctx.value.name if ctx.value else None, hue=hue.name,
                reason=f"One line per '{hue.name}' ({hue.unique} lines)."))
            add(60, PanelSpec("stream_graph", x=t.name, y=ctx.value.name if ctx.value else None, hue=hue.name,
                reason="Shows broad rises and falls of each group; not for exact values."))
        if f"{t.name}_year" in names and f"{t.name}_month" in names:
            add(78, PanelSpec("heatmap", x=f"{t.name}_month", hue=f"{t.name}_year", y=ctx.value.name if ctx.value else None,
                options={"order": "label"}, reason="Year by month grid: shows seasons and growth at once."))
        if ctx.df is not None:
            span = pd.to_datetime(ctx.df[t.name], errors="coerce").agg(["min", "max"])
            days = (span["max"] - span["min"]).days if span.notna().all() else 0
            if 60 <= days <= 800:
                add(64, PanelSpec("calendar", x=t.name, y=ctx.value.name if ctx.value else None,
                    reason="Day-by-day view of the most recent year: weekly patterns and busy days stand out."))
    for c in ctx.years[:1]:
        add(80 if not ctx.times else 66, PanelSpec("line_graph", x=c.name, reason=f"How many rows there are for each '{c.name}'."))
        if ctx.small_cats:
            add(70 if not ctx.times else 60, PanelSpec("line_graph", x=c.name, hue=ctx.small_cats[0].name,
                reason=f"Rows per '{c.name}', one line per '{ctx.small_cats[0].name}'."))


def _ranking_rules(ctx: Context, add) -> None:
    for i, c in enumerate(ctx.many[:4]):
        if (bar := _top_bar(ctx, c)) is not None:
            add(80 - 2 * i, bar)
    pool = [c for c in ctx.cats if c.unique >= 4 and not c.ordinal]  # ranking three classes says little
    for i, g in enumerate(pool[:2]):
        y = _additive(ctx)
        add(74 - i, PanelSpec("lollipop_chart", x=g.name, y=y, reason=f"Ranks the {g.unique} values of '{g.name}'" + (f" by {y}." if y else ".")))
        add(64 - i, PanelSpec("dot_plot", x=g.name, y=y, reason="Dots on a common scale; does not need to start at zero."))
        if y:
            add(54 - i, PanelSpec("span_chart", x=g.name, y=y, reason=f"The min-to-max range of '{y}' for each '{g.name}'."))


def _quality_rules(ctx: Context, add) -> None:
    gaps = [c for c in ctx.prof.columns if c.missing]
    worst = max((c.missing_pct for c in gaps), default=0)
    add(56 + min(worst, 34) if gaps else 40, PanelSpec("missing_values_map",
        reason=(f"{len(gaps)} column(s) have missing values, up to {worst:g}% in one column." if gaps
                else "No missing values found; this confirms it.")))
    for c in sorted(ctx.measures, key=lambda c: -c.outlier_pct)[:3]:
        if c.outlier_pct >= 0.5:
            add(66 + min(c.outlier_pct, 20), PanelSpec("box_whisker_plot", y=c.name, options=_log_opts(y=c),
                reason=f"{c.outlier_pct:.1f}% of '{c.name}' are outliers (outside 1.5 × IQR)."))
    for c in [c for c in ctx.prof.numeric if c.capped_pct][:2]:
        add(74, PanelSpec("histogram", x=c.name, bins=50,
            reason=f"{c.capped_pct:g}% of rows sit exactly at the maximum of '{c.name}': the spike at the right edge is a cap."))


def _geo_rules(ctx: Context, add) -> None:
    geo = _latlon(ctx.prof)
    if not geo:
        return
    colour = ctx.target.column if ctx.target else (ctx.value.name if ctx.value else None)
    sized = [c for c in ctx.measures if _SIZE_HINT.search(c.name) and c.name != colour]
    sized.sort(key=lambda c: next(i for i, w in enumerate(("population", "households", "count", "volume", "visitors", "size", "total", ""))
                                  if w in c.name.lower()))
    size = sized[0].name if sized else None
    if size:
        add(86, PanelSpec("bubble_map", x=geo[0], y=geo[1], size=size, hue=colour,
            reason=f"Found longitude and latitude: points sized by '{size}'" + (f" and coloured by '{colour}'." if colour else ".")))
    add(82, PanelSpec("dot_map", x=geo[0], y=geo[1], hue=colour or (ctx.small_cats[0].name if ctx.small_cats else None),
        reason="Found longitude and latitude: where the rows are" + (f", coloured by '{colour}'." if colour else ".")))


def _text_rules(ctx: Context, add) -> None:
    free = sorted((c for c in ctx.prof.text if c.avg_words >= 6 and not _name_list(ctx, c)), key=lambda c: -c.avg_words)
    for i, c in enumerate(free[:1]):
        add(62, PanelSpec("word_frequency_bar", x=c.name, reason=f"'{c.name}' is free text; the most common words, counted exactly."))
        add(58, PanelSpec("word_cloud", x=c.name, reason=f"A quick feel for the words in '{c.name}' (sizes are approximate)."))


def _pick(out: list[tuple[float, PanelSpec]], goal: str, limit: int, keep_order: bool = False) -> list[PanelSpec]:
    if not keep_order:
        out.sort(key=lambda t: -t[0])
    picked: list[PanelSpec] = []
    seen: set[str] = set()
    per_chart: dict[str, int] = {}
    per_x: dict[str, int] = {}
    cap = {"explore": 2, "target": 6}.get(goal, 5)
    for score, panel in out:
        roles = sorted(v for v in (panel.x, panel.y) if v) if panel.chart in ("scatterplot", "hexbin_plot") else [panel.x, panel.y]
        ignore = {"score", "log"} if panel.chart in ("scatterplot", "hexbin_plot") else {"score"}
        key = f"{panel.chart}{roles}{panel.hue}{panel.size}{panel.columns}" + str(sorted((k, v) for k, v in panel.options.items() if k not in ignore))
        if key in seen or per_chart.get(panel.chart, 0) >= cap or (panel.x and per_x.get(panel.x, 0) >= 3 and goal != "target"):
            continue
        seen.add(key)
        per_chart[panel.chart] = per_chart.get(panel.chart, 0) + 1
        if panel.x:
            per_x[panel.x] = per_x.get(panel.x, 0) + 1
        panel.options.setdefault("score", round(score))
        picked.append(panel)
        if len(picked) >= limit:
            break
    return picked
