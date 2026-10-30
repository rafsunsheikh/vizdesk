"""Rule-based cleaning and normalization suggestions.

Each suggestion is a CleaningStep: a plain dict-able record of an action and
its columns. Steps are saved inside every figure recipe, so a redraw from the
raw file repeats exactly the same cleaning.

"safe" steps only fix how values are stored (types, stray spaces, empty
columns). They never change what the data says, so auto mode applies them by
default. Every other step is offered, not applied.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from vizdesk.data import (
    CATEGORICAL,
    DATETIME,
    IDENTIFIER,
    CONSTANT,
    EMPTY,
    NUMERIC,
    TEXT,
    DatasetProfile,
    parse_datetime,
    parse_numeric,
)


_GEO_NAME = re.compile(r"^(lat|latitude|lon|lng|long|longitude)$", re.IGNORECASE)
_BIN_HINT = re.compile(r"(age|tenure|duration|length|income|salary|days|months|years|experience|fare|price)", re.IGNORECASE)


def _fmt(value) -> str:
    return f"{value:,.0f}" if value is not None and abs(value) >= 100 else f"{value:g}"


def nice_edges(values: pd.Series, groups: int = 6) -> list[float]:
    """Round range edges, e.g. 0, 10, 20 ... for ages 0.4 to 80."""
    lo, hi = float(values.min()), float(values.max())
    raw = (hi - lo) / groups or 1
    base = 10 ** math.floor(math.log10(raw))
    width = next(m * base for m in (1, 2, 2.5, 5, 10) if m * base >= raw)
    start = math.floor(lo / width) * width
    return [start + i * width for i in range(int(math.ceil((hi - start) / width)) + 1)] or [lo, hi]


@dataclass
class CleaningStep:
    action: str
    columns: list[str]
    title: str
    reason: str
    safe: bool = False
    params: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.action}:{','.join(self.columns)}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CleaningStep:
        return cls(**d)


def suggest_cleaning(prof: DatasetProfile) -> list[CleaningStep]:
    steps: list[CleaningStep] = []
    add = steps.append

    for c in prof.columns:
        if c.kind == EMPTY:
            add(CleaningStep("drop_columns", [c.name], f"Drop empty column '{c.name}'", "Every value is missing.", safe=True))
            continue
        if c.kind == IDENTIFIER and re.fullmatch(r"unnamed: ?\d+", c.name, re.IGNORECASE):
            add(CleaningStep("drop_columns", [c.name], f"Drop leftover index column '{c.name}'",
                             "A row number saved by an earlier pandas export (`to_csv` without index=False). It holds no information.",
                             safe=True))
            continue
        if c.has_padding and (c.kind != TEXT or c.blanks):  # stray spaces only change results in labels, numbers and dates
            why = (f"{c.blanks} values are only spaces; they will count as missing." if c.blanks else
                   "Some values have spaces at the start or end, so ' Sydney' and 'Sydney' count as different.")
            add(CleaningStep("strip_whitespace", [c.name], f"Trim spaces in '{c.name}'", why, safe=True))
        if c.numeric_like:
            examples = ", ".join(f"'{v}'" for v in c.top_values[:2])
            add(CleaningStep("to_numeric", [c.name], f"Convert '{c.name}' to numbers",
                             f"Stored as text but the values are numbers (for example {examples}). Symbols like $ , % are removed"
                             + (f" and the {c.blanks} blank values become missing." if c.blanks else "."), safe=True))
        if c.units:
            add(CleaningStep("split_number_unit", [c.name], f"Split '{c.name}' into a number and a unit",
                             f"Values look like '90 min' or '2 seasons' (units: {', '.join(c.units)}). This adds '{c.name}_value' "
                             f"(a number you can chart) and '{c.name}_unit'.", safe=True))
        if c.datetime_like:
            add(CleaningStep("to_datetime", [c.name], f"Convert '{c.name}' to dates",
                             "Stored as text but at least 90% of values parse as dates.", safe=True))
        if c.kind == CONSTANT:
            add(CleaningStep("drop_columns", [c.name], f"Drop constant column '{c.name}'",
                             f"Every row has the same value ('{c.top_values[0] if c.top_values else ''}'), so it cannot explain any differences."))
        if c.case_variants > 0:
            add(CleaningStep("lowercase", [c.name], f"Merge case variants in '{c.name}'",
                             f"{c.case_variants} categories differ only by upper/lower case (for example 'NSW' vs 'nsw')."))
        if c.missing_pct >= 60 and c.kind != EMPTY:
            add(CleaningStep("drop_columns", [c.name], f"Drop mostly-empty column '{c.name}'",
                             f"{c.missing_pct:.0f}% of values are missing; filling that many would be mostly guesswork."))
        elif c.missing > 0 and c.kind == NUMERIC:
            skewed = c.skew is not None and abs(c.skew) > 1
            how = "median" if skewed else "mean"
            add(CleaningStep("fill_missing", [c.name], f"Fill {c.missing} missing in '{c.name}' with the {how}",
                             f"{c.missing_pct:.1f}% missing. The {how} is used because the column is "
                             f"{'skewed, and the median is not pulled by extreme values' if skewed else 'roughly symmetric'}.",
                             params={"method": how}))
        elif c.missing > 0 and (c.is_category or c.kind == TEXT):
            add(CleaningStep("fill_missing", [c.name], f"Fill {c.missing} missing in '{c.name}' with 'Unknown'",
                             f"{c.missing_pct:.1f}% missing. A visible 'Unknown' group keeps those rows in counts instead of hiding them.",
                             params={"method": "constant", "value": "Unknown"}))
        if c.capped_pct:
            add(CleaningStep("drop_capped", [c.name], f"Remove rows where '{c.name}' sits at its cap ({_fmt(c.max)})",
                             f"{c.capped_pct:g}% of rows have exactly the maximum value {_fmt(c.max)}, far more than any other "
                             "value. That usually means values above it were cut off at collection, so these rows hide their real "
                             "value and pile up in one bar."))
        if c.kind == DATETIME:
            add(CleaningStep("date_parts", [c.name], f"Add year and month columns from '{c.name}'",
                             f"Adds '{c.name}_year' and '{c.name}_month' so you can compare years or seasons "
                             "(for example a year by month heatmap)."))
        if c.kind == NUMERIC and _BIN_HINT.search(c.name) and not c.is_year and c.unique > 12:
            add(CleaningStep("bin", [c.name], f"Group '{c.name}' into ranges (adds '{c.name}_group')",
                             f"Turns '{c.name}' into a few ranges (like 0-10, 10-20) so you can compare groups, for example "
                             "the share of a target in each age band."))
        if c.kind == NUMERIC and 0.1 <= c.outlier_pct <= 5:
            add(CleaningStep("clip_outliers", [c.name], f"Cap outliers in '{c.name}'",
                             f"{c.outlier_pct:.1f}% of values fall outside 1.5 x IQR. Capping keeps the rows but stops a few extremes "
                             "from squashing the rest of the chart. Check first that they are errors, not real events."))
        if c.kind == NUMERIC and c.skew is not None and c.skew > 1.5 and c.all_positive:
            add(CleaningStep("log_transform", [c.name], f"Log-transform '{c.name}' (adds '{c.name}_log')",
                             f"Strong right skew ({c.skew:.1f}): most values are small with a long tail of big ones. "
                             "A log scale spreads them out. The original column is kept."))
        if c.kind == CATEGORICAL and 15 < c.unique <= 200 and c.rare_share >= 0.3:
            add(CleaningStep("group_rare", [c.name], f"Group rare categories in '{c.name}' into 'Other'",
                             f"{c.unique} categories and {c.rare_share:.0%} of them cover under 1% of rows each. "
                             "Grouping keeps bar and pie charts readable.", params={"min_share": 0.01}))

    if prof.duplicate_rows:
        add(CleaningStep("drop_duplicates", [], f"Remove {prof.duplicate_rows} duplicate rows",
                         "These rows are exact copies of another row. Keep them only if repeats are real (for example two identical orders)."))

    numeric = [c for c in prof.numeric if c.is_measure and not _GEO_NAME.search(c.name)]
    if len(numeric) >= 3:
        spans = [(c.max - c.min) for c in numeric if c.max is not None and c.min is not None and c.max > c.min]
        if spans and max(spans) / max(min(spans), 1e-12) >= 100:
            names = [c.name for c in numeric]
            add(CleaningStep("standardize", names, "Standardize numeric columns (z-score, adds '_z' columns)",
                             "The numeric columns are on very different scales "
                             f"(ranges from {min(spans):.3g} to {max(spans):.3g}). For radar, parallel coordinates or "
                             "side-by-side comparisons, z-scores put them on one scale. Originals are kept."))
            add(CleaningStep("min_max_scale", names, "Scale numeric columns to 0-1 (adds '_scaled' columns)",
                             "Same reason as above. Choose 0-1 scaling instead of z-scores when you want every column to keep its "
                             "shape and fit between 0 and 1. Originals are kept."))
    return steps


def apply_step(df: pd.DataFrame, step: CleaningStep) -> pd.DataFrame:
    out = df.copy()
    cols = [c for c in step.columns if c in out.columns]
    a = step.action
    if a == "drop_columns":
        out = out.drop(columns=cols)
    elif a == "strip_whitespace":
        for c in cols:
            out[c] = out[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    elif a == "to_numeric":
        for c in cols:
            out[c] = parse_numeric(out[c])
    elif a == "to_datetime":
        for c in cols:
            out[c] = parse_datetime(out[c].astype("string").str.strip())
    elif a == "lowercase":
        for c in cols:
            out[c] = out[c].map(lambda v: v.strip().lower() if isinstance(v, str) else v)
    elif a == "fill_missing":
        method = step.params.get("method", "median")
        for c in cols:
            if method == "constant":
                out[c] = out[c].astype(object).where(out[c].notna(), step.params.get("value", "Unknown"))
            else:
                values = pd.to_numeric(out[c], errors="coerce")
                out[c] = values.fillna(values.median() if method == "median" else values.mean())
    elif a == "clip_outliers":
        for c in cols:
            values = pd.to_numeric(out[c], errors="coerce")
            q1, q3 = values.quantile([0.25, 0.75])
            iqr = q3 - q1
            out[c] = values.clip(q1 - 1.5 * iqr, q3 + 1.5 * iqr)
    elif a == "log_transform":
        for c in cols:
            values = pd.to_numeric(out[c], errors="coerce")
            out[f"{c}_log"] = np.log(values.where(values > 0))
    elif a == "group_rare":
        share = step.params.get("min_share", 0.01)
        for c in cols:
            freq = out[c].value_counts(normalize=True)
            rare = set(freq[freq < share].index)
            out[c] = out[c].map(lambda v: "Other" if v in rare else v)
    elif a == "drop_duplicates":
        out = out.drop_duplicates().reset_index(drop=True)
    elif a == "standardize":
        for c in cols:
            values = pd.to_numeric(out[c], errors="coerce")
            sd = values.std()
            out[f"{c}_z"] = (values - values.mean()) / sd if sd else 0.0
    elif a == "min_max_scale":
        for c in cols:
            values = pd.to_numeric(out[c], errors="coerce")
            span = values.max() - values.min()
            out[f"{c}_scaled"] = (values - values.min()) / span if span else 0.0
    elif a == "split_number_unit":
        for c in cols:
            parts = out[c].astype("string").str.extract(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\.?\s*$")
            out[f"{c}_value"] = pd.to_numeric(parts[0], errors="coerce")
            out[f"{c}_unit"] = parts[1].str.lower().str.rstrip("s")
    elif a == "drop_capped":
        for c in cols:
            values = pd.to_numeric(out[c], errors="coerce")
            out = out[values != values.max()].reset_index(drop=True)
    elif a == "date_parts":
        for c in cols:
            when = parse_datetime(out[c])
            out[f"{c}_year"] = when.dt.year.astype("Int64")
            out[f"{c}_month"] = when.dt.month.astype("Int64")
    elif a == "bin":
        for c in cols:
            values = pd.to_numeric(out[c], errors="coerce")
            edges = step.params.get("edges") or nice_edges(values.dropna())
            labels = [f"{_fmt(a)}-{_fmt(b)}" for a, b in zip(edges[:-1], edges[1:])]
            out[f"{c}_group"] = pd.cut(values, edges, labels=labels, include_lowest=True).astype("string")
    else:
        raise ValueError(f"unknown cleaning action '{a}'")
    return out


def apply_steps(df: pd.DataFrame, steps: list[CleaningStep]) -> pd.DataFrame:
    for step in steps:
        df = apply_step(df, step)
    return df
