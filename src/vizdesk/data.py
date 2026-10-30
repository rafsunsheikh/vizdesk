"""Load CSV / Excel files and profile their columns.

The profile is what every rule-based suggestion works from: for each column
we work out a "kind" (numeric, categorical, datetime, ...) plus the facts the
cleaning and chart rules need (missing share, skew, outliers, and so on).
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
SUPPORTED_SUFFIXES = CSV_SUFFIXES | EXCEL_SUFFIXES

NUMERIC, CATEGORICAL, DATETIME, BOOLEAN, TEXT, IDENTIFIER, CONSTANT, EMPTY = (
    "numeric",
    "categorical",
    "datetime",
    "boolean",
    "text",
    "identifier",
    "constant",
    "empty",
)

_NUMBER_JUNK = re.compile(r"[,\s$€£¥%]")
# "id", "order_id", "Customer ID", "customerID", "Postal Code", "Unnamed: 0" ...
_ID_NAME = re.compile(r"((^|[\s_\-.])(id|uuid|guid|key|no|number)$|^id[\s_]|^index$|^unnamed: ?\d+$|zip|postal|postcode)", re.IGNORECASE)
_CAMEL_ID = re.compile(r"[a-z]ID$")
_YEAR_NAME = re.compile(r"year", re.IGNORECASE)
_NUMBER_UNIT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\.?\s*$")
_MAX_CATEGORIES = 30
_SAMPLE = 2000  # values used for type sniffing on large columns


def find_data_files(path: str | Path) -> list[Path]:
    """A file returns itself; a folder returns every CSV/Excel file inside it."""
    p = Path(path).expanduser()
    if p.is_dir():
        return sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_SUFFIXES and f.is_file() and not _junk(f.relative_to(p)))
    if not p.exists():
        raise FileNotFoundError(f"no such file or folder: {p}")
    if p.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file type '{p.suffix}'. Use CSV or Excel ({', '.join(sorted(SUPPORTED_SUFFIXES))}).")
    return [p]


def _junk(relative: Path) -> bool:
    """Skip macOS archive metadata (__MACOSX, ._file.csv), hidden folders and Excel lock files (~$book.xlsx)."""
    return any(part.startswith((".", "__MACOSX")) for part in relative.parts) or relative.name.startswith(("._", "~$"))


def list_sheets(path: str | Path) -> list[str]:
    p = Path(path).expanduser()
    if p.suffix.lower() in EXCEL_SUFFIXES:
        with pd.ExcelFile(p) as book:
            return list(book.sheet_names)
    return []


def load_table(path: str | Path, sheet: str | None = None) -> pd.DataFrame:
    """Read one table. For Excel files the first sheet is used unless one is named."""
    p = Path(path).expanduser()
    suffix = p.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        df = pd.read_excel(p, sheet_name=sheet if sheet else 0)
    elif suffix in CSV_SUFFIXES:
        # sep=None sniffs commas, semicolons and tabs.
        df = pd.read_csv(p, sep=None, engine="python", encoding_errors="replace")
    else:
        raise ValueError(f"unsupported file type '{p.suffix}'")
    df.columns = [str(c).strip() or f"column_{i}" for i, c in enumerate(df.columns)]
    return df


@dataclass
class ColumnProfile:
    name: str
    kind: str
    dtype: str
    count: int
    missing: int
    unique: int
    missing_pct: float
    numeric_like: bool = False  # text that would parse as numbers ("$1,200")
    datetime_like: bool = False  # text that would parse as dates
    skew: float | None = None
    outlier_pct: float = 0.0
    min: float | None = None
    max: float | None = None
    std: float | None = None
    all_positive: bool = False
    has_padding: bool = False  # leading / trailing spaces
    case_variants: int = 0  # categories that differ only by case
    rare_share: float = 0.0  # share of categories with < 1% of rows
    avg_length: float = 0.0  # mean label length in characters
    avg_words: float = 0.0
    blanks: int = 0  # values that are only spaces, counted as missing
    ordinal: bool = False  # few whole numbers (1, 2, 3): a category with a natural order
    is_year: bool = False  # whole numbers named "...year..." between 1800 and 2100
    multi_valued: bool = False  # comma-separated lists, e.g. "Drama, Comedy"
    item_unique: int = 0  # distinct items after splitting a multi-valued column
    units: list[str] = field(default_factory=list)  # "90 min", "2 Seasons" -> ["min", "season"]
    capped_pct: float = 0.0  # share of rows sitting exactly at the maximum
    top_values: list[str] = field(default_factory=list)

    @property
    def is_numeric(self) -> bool:
        return self.kind == NUMERIC

    @property
    def is_category(self) -> bool:
        return self.kind in (CATEGORICAL, BOOLEAN)

    @property
    def is_measure(self) -> bool:
        """A numeric column worth averaging or summing (not a year, not constant)."""
        return self.kind == NUMERIC and not self.is_year and bool(self.std)

    @property
    def summary(self) -> str:
        if self.kind == NUMERIC and self.min is not None:
            return f"{self.min:.4g} to {self.max:.4g}" + (f" ({self.capped_pct:g}% at the max)" if self.capped_pct else "")
        if self.multi_valued:
            return f"lists of {self.item_unique} items, e.g. {', '.join(self.top_values[:1])}"
        if self.units:
            return f"number + unit ({', '.join(self.units)})"
        if self.top_values:
            return ", ".join(self.top_values[:3])
        return ""


@dataclass
class DatasetProfile:
    rows: int
    columns: list[ColumnProfile]
    duplicate_rows: int

    def by_kind(self, *kinds: str) -> list[ColumnProfile]:
        return [c for c in self.columns if c.kind in kinds]

    @property
    def numeric(self) -> list[ColumnProfile]:
        return self.by_kind(NUMERIC)

    @property
    def categorical(self) -> list[ColumnProfile]:
        return self.by_kind(CATEGORICAL, BOOLEAN)

    @property
    def datetime(self) -> list[ColumnProfile]:
        return self.by_kind(DATETIME)

    @property
    def text(self) -> list[ColumnProfile]:
        return self.by_kind(TEXT)

    def get(self, name: str) -> ColumnProfile:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)


def parse_numeric(series: pd.Series) -> pd.Series:
    """'$1,200' -> 1200.0, '15%' -> 15.0, '(30)' stays NaN."""
    cleaned = series.astype("string").str.replace(_NUMBER_JUNK, "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def parse_datetime(series: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, errors="coerce", format="mixed")


def _is_sequence(values: pd.Series) -> bool:
    """Whole numbers that count up by one (1, 2, 3 ...), like a row number."""
    if not pd.api.types.is_integer_dtype(values):
        return False
    steps = np.diff(np.sort(values.unique()))
    return bool(len(steps)) and bool((steps == 1).all())


def _is_texty(series: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)


def _sample(values: pd.Series, n: int = _SAMPLE) -> pd.Series:
    return values if len(values) <= n else values.sample(n, random_state=0)


def _id_name(name: str) -> bool:
    return bool(_ID_NAME.search(name) or _CAMEL_ID.search(name))


def _numeric_facts(prof: ColumnProfile, values: pd.Series) -> None:
    values = values.astype(float).dropna()
    if not len(values):
        return
    prof.min, prof.max = float(values.min()), float(values.max())
    prof.std = float(values.std()) if len(values) > 1 else 0.0
    prof.all_positive = bool((values > 0).all())
    prof.skew = float(values.skew()) if len(values) > 2 else 0.0
    q1, q3 = values.quantile([0.25, 0.75])
    iqr = q3 - q1
    if iqr > 0:
        outside = (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)
        prof.outlier_pct = round(100 * float(outside.mean()), 2)
    at_max = float((values == prof.max).mean())
    if prof.unique >= 20 and at_max >= 0.02 and values.quantile(0.9) < prof.max:
        prof.capped_pct = round(100 * at_max, 2)


def _profile_column(name: str, s: pd.Series, rows: int) -> ColumnProfile:
    non_null = s.dropna()
    blanks = 0
    if _is_texty(s) and len(non_null):
        empty = non_null.astype(str).str.strip() == ""
        blanks = int(empty.sum())
        non_null = non_null[~empty]
    count = int(non_null.shape[0])
    missing = rows - count
    unique = int(non_null.nunique())
    prof = ColumnProfile(
        name=name,
        kind=EMPTY,
        dtype=str(s.dtype),
        count=count,
        missing=missing,
        unique=unique,
        missing_pct=round(100 * missing / rows, 2) if rows else 0.0,
        blanks=blanks,
    )
    if count == 0:
        return prof
    if unique == 1:
        prof.kind = CONSTANT
        prof.top_values = [str(non_null.iloc[0])]
        return prof
    many = unique > _MAX_CATEGORIES and unique >= 0.05 * count

    if pd.api.types.is_bool_dtype(s):
        prof.kind = BOOLEAN
    elif pd.api.types.is_datetime64_any_dtype(s):
        prof.kind = DATETIME
    elif pd.api.types.is_numeric_dtype(s):
        prof.kind = NUMERIC
        whole = bool((non_null == np.round(non_null)).all())
        if (unique >= 0.9 * count and count > _MAX_CATEGORIES and _is_sequence(non_null)) or (_id_name(name) and many):
            prof.kind = IDENTIFIER
        elif unique == 2:
            prof.kind = BOOLEAN
        elif whole and unique <= 7:
            prof.kind, prof.ordinal = CATEGORICAL, True
        elif whole and _YEAR_NAME.search(name) and 1800 <= non_null.min() and non_null.max() <= 2100:
            prof.is_year = True
    elif _is_texty(s):
        as_text = non_null.astype(str)
        stripped = as_text.str.strip()
        prof.has_padding = bool((as_text != stripped).any()) or blanks > 0
        sample = _sample(stripped)
        prof.avg_words = round(float(sample.str.split().str.len().mean()), 2)
        prof.avg_length = round(float(sample.str.len().mean()), 1)
        looks_numeric = parse_numeric(sample).notna().mean() >= 0.9
        if looks_numeric:
            prof.numeric_like = True
            prof.kind = NUMERIC
            prof.top_values = [v for v in sample.drop_duplicates().head(3)]  # examples for the cleaning message
        elif _looks_like_dates(sample):
            prof.datetime_like = True
            prof.kind = DATETIME
        else:
            prof.kind = _text_kind(name, prof, stripped, sample, many)
    else:
        prof.kind = CATEGORICAL

    if prof.kind == NUMERIC:
        _numeric_facts(prof, parse_numeric(non_null) if prof.numeric_like else non_null)
        if prof.is_year:
            prof.capped_pct = 0.0
    if prof.kind in (CATEGORICAL, BOOLEAN, TEXT, IDENTIFIER):
        counts = non_null.astype(str).str.strip().value_counts()
        if prof.ordinal:
            counts = counts.sort_index(key=lambda idx: pd.to_numeric(idx, errors="coerce"))
        prof.top_values = [str(v) for v in counts.index[:5]]
        prof.rare_share = round(float((counts / count < 0.01).mean()), 3)
        prof.avg_length = prof.avg_length or round(float(_sample(non_null.astype(str)).str.len().mean()), 1)
        if prof.kind == CATEGORICAL and not prof.ordinal:
            prof.case_variants = int(counts.index.nunique() - counts.index.str.lower().nunique())
    return prof


def _looks_like_dates(sample: pd.Series) -> bool:
    """Short values with digits that mostly parse as dates. Pure numbers are not dates."""
    if sample.str.len().mean() > 40 or sample.str.contains(r"\d").mean() < 0.9:
        return False
    if sample.str.fullmatch(r"-?\d+(\.\d+)?").all():
        return False
    distinct = sample.drop_duplicates()
    distinct = distinct if len(distinct) <= 500 else distinct.sample(500, random_state=0)
    return parse_datetime(distinct).notna().mean() >= 0.9


def _text_kind(name: str, prof: ColumnProfile, stripped: pd.Series, sample: pd.Series, many: bool) -> str:
    """Decide between identifier, free text, a number-with-unit, a list column and a category."""
    count, unique = prof.count, prof.unique
    has_digits = sample.str.contains(r"\d").mean()
    if many and (_id_name(name) or (prof.avg_words <= 2 and has_digits >= 0.5 and unique >= 0.5 * count)):
        return IDENTIFIER  # order numbers, ticket codes, cabin numbers ...
    units = sample.str.extract(_NUMBER_UNIT)
    if units[0].notna().mean() >= 0.9:
        names = units[1].dropna().str.lower().str.rstrip("s")
        if names.nunique() <= 5:
            prof.units = sorted(names.unique())
            return CATEGORICAL
    if prof.avg_words >= 6:
        return TEXT  # descriptions, reviews, comments
    if sample.str.contains(",").mean() >= 0.15:
        # Lists repeat the same few items across many distinct values ("Drama, Comedy", "Comedy, Horror").
        # Product names with commas do not, so judge on distinct values, not rows.
        items = pd.Series(stripped.unique()).str.split(",").explode().str.strip()
        items = items[items != ""]
        if len(items) and items.nunique() <= 0.3 * len(items):
            prof.multi_valued = True
            prof.item_unique = int(items.nunique())
            return CATEGORICAL
    if unique >= 0.9 * count and count > _MAX_CATEGORIES:
        return TEXT  # titles and names: nearly every row differs
    return CATEGORICAL if unique > 2 else BOOLEAN


def profile(df: pd.DataFrame) -> DatasetProfile:
    rows = int(df.shape[0])
    cols = [_profile_column(str(name), df[name], rows) for name in df.columns]
    try:
        dupes = int(df.duplicated().sum())
    except TypeError:  # unhashable cells, for example lists from JSON-ish Excel exports
        dupes = 0
    return DatasetProfile(rows=rows, columns=cols, duplicate_rows=dupes)


def coerce_types(df: pd.DataFrame, prof: DatasetProfile) -> pd.DataFrame:
    """Convert text columns that are really numbers or dates. Used before drawing."""
    out = df.copy()
    for c in prof.columns:
        if c.numeric_like:
            out[c.name] = parse_numeric(out[c.name])
        elif c.datetime_like:
            out[c.name] = parse_datetime(out[c.name].astype("string").str.strip())
    return out


def numeric_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df[columns].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
