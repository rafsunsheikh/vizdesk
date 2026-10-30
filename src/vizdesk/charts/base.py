"""Shared pieces for chart renderers: the registry, column roles and helpers.

Each chart is a function registered with @chart. The registry records which
column "roles" a chart takes (x, y, hue, size, columns) and what kind of
column fits each role. The suggestion engine, the TUI editor and validation
all read those roles, so registering a chart here is enough to make it
selectable everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from vizdesk.spec import PanelSpec

MISSING = "(missing)"

# Role kinds: "num", "cat", "time", "text", "any". A trailing "+" on columns
# means "a list of columns of this kind".
NUM, CAT, TIME, TEXT, ANY = "num", "cat", "time", "text", "any"

_SUM_HINT = re.compile(r"(sales|revenue|amount|total|count|qty|quantity|units|spend|volume|profit|orders|visits)", re.I)
AGG_HELP = "agg=auto sums columns that look like totals (sales, revenue, units...) and averages the rest."
_STOPWORDS = set(
    "a an and are as at be but by for from has have i if in into is it its of on or so that the their them then there "
    "these they this to was were will with you your we our not no yes very just also can than too all any been do does "
    "did my me he she his her him what which who when where why how".split()
)


@dataclass
class Renderer:
    key: str
    func: Callable
    roles: dict[str, tuple[str, bool]]  # role -> (kind, required)
    polar: bool = False
    hint: str = ""
    check: Callable | None = None  # (df, panel) -> list of problems, for rules roles cannot express
    options: str = ""  # the options this chart reads, shown in the editor

    def required(self) -> list[str]:
        return [r for r, (_, req) in self.roles.items() if req]


REGISTRY: dict[str, Renderer] = {}


def chart(key: str, polar: bool = False, hint: str = "", check: Callable | None = None, options: str = "",
          **roles: tuple[str, bool]):
    def wrap(func):
        REGISTRY[key] = Renderer(key, func, roles, polar, hint, check, options)
        return func

    return wrap


def need_columns(n: int, what: str) -> Callable:
    """A check that the panel lists at least `n` columns."""
    def check(df: pd.DataFrame, p: PanelSpec) -> list[str]:
        return [] if len(p.columns) >= n else [f"needs {what} in 'columns' ({len(p.columns)} given)."]

    return check


def _opt(p: PanelSpec, key: str, default, cast=float):
    """Read a panel option (options are typed in as text, so cast them)."""
    value = p.options.get(key)
    if value in (None, ""):
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def apply_filter(df: pd.DataFrame, p: PanelSpec) -> pd.DataFrame:
    """Per-panel row preparation, from the panel options:
    filter='Name=AAPL' or 'region=North|South' keeps only matching rows;
    split='listed_in' turns "Drama, Comedy" into one row per item, so each item is counted."""
    split = p.options.get("split")
    if split:
        if split not in df.columns:
            raise ValueError(f"split column '{split}' is not in the data")
        df = df.assign(**{split: df[split].astype("string").str.split(",")}).explode(split)
        df[split] = df[split].str.strip()
        df = df[df[split].notna() & (df[split] != "")]
    rule = p.options.get("filter")
    if not rule or "=" not in str(rule):
        return df
    col, _, values = str(rule).partition("=")
    col = col.strip()
    if col not in df.columns:
        raise ValueError(f"filter column '{col}' is not in the data")
    wanted = {v.strip() for v in values.split("|")}
    return df[df[col].astype(str).str.strip().isin(wanted)]


# ---------------------------------------------------------------- helpers


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _agg_name(p: PanelSpec) -> str:
    if p.agg != "auto":
        return p.agg
    if not p.y:
        return "count"
    return "sum" if _SUM_HINT.search(p.y) else "mean"


def _aggregate(df: pd.DataFrame, by: str | list[str], p: PanelSpec) -> pd.Series:
    """y aggregated per group (or row counts). Missing group labels show as '(missing)', not 'nan'."""
    keys = list(by) if isinstance(by, (list, tuple)) else [by]  # by may also be a pd.Grouper for time series
    labelled = df.assign(**{k: df[k].astype(object).where(df[k].notna(), MISSING) for k in keys if isinstance(k, str)
                            and k in df and not pd.api.types.is_datetime64_any_dtype(df[k])})
    agg = _agg_name(p)
    # sort=False: labels can mix numbers and '(missing)'; callers order the result themselves.
    if agg == "count" or not p.y:
        return labelled.groupby(by, observed=True, sort=False).size()
    values = labelled.assign(_v=_num(df, p.y))
    return values.groupby(by, observed=True, sort=False)["_v"].agg(agg)


def _log_axes(p: PanelSpec) -> str:
    """options log=x, log=y or log=xy."""
    return str(p.options.get("log", "")).lower()


def _log_bins(values: pd.Series, n: int) -> tuple[np.ndarray, str]:
    """Bin edges and axis scale for a long-tailed column: log when all values are positive,
    symlog (linear near zero, log above) when there are zeros."""
    lo, hi = float(values.min()), float(values.max())
    if lo > 0:
        return np.geomspace(lo, hi, n + 1), "log"
    return np.expm1(np.linspace(np.log1p(max(lo, 0)), np.log1p(hi), n + 1)), "symlog"


def _flag(p: PanelSpec, key: str, default: bool) -> bool:
    value = p.options.get(key)
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def _pivot_wide(df: pd.DataFrame, p: PanelSpec, rows: int, cols: int) -> pd.DataFrame:
    """x down the side, hue across the top, the aggregated value in the cells; biggest first."""
    wide = _aggregate(df, [p.x, p.hue], p).unstack(p.hue).fillna(0)
    keep_rows = _order(wide.sum(axis=1).sort_values(ascending=False).iloc[:rows], p).index
    keep_cols = wide.sum(axis=0).sort_values(ascending=False).index[:cols]
    return wide.loc[keep_rows, keep_cols]


def _value_label(p: PanelSpec) -> str:
    agg = _agg_name(p)
    return "count" if agg == "count" or not p.y else f"{agg} of {p.y}"


def _top(series: pd.Series, n: int, other: bool = False) -> pd.Series:
    series = series.sort_values(ascending=False)
    if len(series) <= n:
        return series
    head = series.iloc[:n]
    if other:
        head = pd.concat([head, pd.Series({"Other": series.iloc[n:].sum()})])
    return head


def _order(series: pd.Series, p: PanelSpec) -> pd.Series:
    """order=label keeps a natural order (class 1, 2, 3; age bands) instead of biggest first."""
    if p.options.get("order") != "label":
        return series
    labels = pd.Series(series.index.astype(str))
    numeric = pd.to_numeric(labels.str.extract(r"^(-?\d+(?:\.\d+)?)")[0], errors="coerce")
    if numeric.notna().any():  # 1, 2, 3 ... or "0-10", "10-20"; labels without a number (like '(missing)') go last
        return series.iloc[np.argsort(numeric.fillna(np.inf).to_numpy(), kind="stable")]
    return series.iloc[np.argsort(labels.to_numpy(), kind="stable")]


def _groups(df: pd.DataFrame, hue: str | None, limit: int = 8):
    """Yield (label, sub-frame) for each of the most common hue values, or the whole frame."""
    if not hue:
        yield None, df
        return
    for value in df[hue].value_counts().index[:limit]:
        yield str(value), df[df[hue] == value]


def _labels(ax, p: PanelSpec, x: str | None = None, y: str | None = None, default_title: str = "") -> None:
    if x is not None:
        ax.set_xlabel(x)
    if y is not None:
        ax.set_ylabel(y)
    ax.set_title(p.title or default_title, fontsize="medium")
    if p.log_y:
        ax.set_yscale("log")


def _rotate_if_crowded(ax, labels) -> None:
    if len(labels) > 5 or max((len(str(l)) for l in labels), default=0) > 8:
        ax.tick_params(axis="x", labelrotation=45)
        for t in ax.get_xticklabels():
            t.set_horizontalalignment("right")


def _rotate_dates(ax) -> None:
    """Rotate this panel's date labels only (fig.autofmt_xdate would hide labels on other panels)."""
    ax.tick_params(axis="x", labelrotation=30)
    for t in ax.get_xticklabels():
        t.set_horizontalalignment("right")


def _short(label, limit: int = 22) -> str:
    """Category labels longer than `limit` squeeze the plot area to nothing, so trim them."""
    text = str(label)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.3g}"


def _time_series(df: pd.DataFrame, p: PanelSpec, by_hue: bool) -> pd.DataFrame | pd.Series:
    """Aggregate y over time, resampling when there are too many timestamps to draw."""
    data = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(data[p.x]) and not pd.api.types.is_numeric_dtype(data[p.x]):
        try:  # numbers such as years stay numbers; text dates become dates
            data[p.x] = pd.to_datetime(data[p.x], errors="coerce", format="mixed")
        except (TypeError, ValueError):
            pass
    data = data.dropna(subset=[p.x])
    key: object = p.x
    if pd.api.types.is_datetime64_any_dtype(data[p.x]) and data[p.x].nunique() > 120:
        span = (data[p.x].max() - data[p.x].min()).days
        freq = p.options.get("freq") or ("h" if span <= 2 else "D" if span <= 120 else "W" if span <= 730 else "MS" if span <= 3650 else "YS")
        key = pd.Grouper(key=p.x, freq=freq)
    keys = [key, p.hue] if by_hue and p.hue else key
    series = _aggregate(data, keys, p)
    if by_hue and p.hue:
        top = data[p.hue].value_counts().index[:8]
        wide = series.unstack(p.hue).sort_index()  # time must run left to right
        return wide[[c for c in wide.columns if c in set(top)]].fillna(0)
    return series.sort_index()


def _kde(values: np.ndarray, grid: np.ndarray) -> np.ndarray | None:
    values = values[np.isfinite(values)]
    if len(values) > 5000:
        values = np.random.default_rng(0).choice(values, 5000, replace=False)
    if len(values) < 2 or values.std() == 0:
        return None
    bw = 1.06 * values.std() * len(values) ** (-1 / 5)
    z = (grid[:, None] - values[None, :]) / bw
    return np.exp(-0.5 * z**2).sum(axis=1) / (len(values) * bw * np.sqrt(2 * np.pi))


def _squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap layout (Bruls, Huizing and van Wijk, 2000)."""
    total = sum(values)
    sizes = [v * w * h / total for v in values]
    rects: list[tuple[float, float, float, float]] = []

    def worst(row: list[float], side: float) -> float:
        s = sum(row)
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row)

    while sizes:
        side = min(w, h)
        row = [sizes.pop(0)]
        while sizes and worst(row + [sizes[0]], side) <= worst(row, side):
            row.append(sizes.pop(0))
        s = sum(row)
        if w >= h:
            cw, cy = s / h, y
            for v in row:
                rects.append((x, cy, cw, v / cw))
                cy += v / cw
            x, w = x + cw, w - cw
        else:
            rh, cx = s / w, x
            for v in row:
                rects.append((cx, y, v / rh, rh))
                cx += v / rh
            y, h = y + rh, h - rh
    return rects



def _ohlc_columns(df: pd.DataFrame, p: PanelSpec) -> list[str]:
    if len(p.columns) >= 4:
        return p.columns[:4]
    lower = {c.lower(): c for c in df.columns}
    return [lower[k] for k in ("open", "high", "low", "close") if k in lower]
