"""High-level steps shared by the CLI and the TUI: scan a file, and the
one-shot "auto" run (scan -> safe cleaning -> suggest -> draw PNGs)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from vizdesk.cleaning import CleaningStep, apply_steps, suggest_cleaning
from vizdesk.data import DatasetProfile, coerce_types, find_data_files, list_sheets, load_table, profile
from vizdesk.render import RenderResult, render_figure
from vizdesk.spec import FigureSpec, PanelSpec
from vizdesk.suggest import suggest


@dataclass
class Layout:
    rows: int = 2
    cols: int = 2
    width: float = 12.0
    height: float = 9.0
    dpi: int = 150
    padding: bool = True
    pad: float = 0.3
    theme: str = "colorblind"
    fmt: str = "png"


@dataclass
class Scan:
    source: Path
    sheet: str | None
    raw: pd.DataFrame
    profile: DatasetProfile
    cleaning: list[CleaningStep]
    data: pd.DataFrame = field(repr=False, default=None)  # after applied cleaning + type coercion
    applied: list[CleaningStep] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.source.stem + (f"-{self.sheet}" if self.sheet else "")

    def apply(self, steps: list[CleaningStep]) -> None:
        """Replace the applied cleaning with `steps` (always from the raw data, so it can be undone)."""
        self.applied = list(steps)
        cleaned = apply_steps(self.raw, self.applied)
        self.profile = profile(cleaned)
        self.data = coerce_types(cleaned, self.profile)
        self.profile = profile(self.data)

    def suggestions(self, goal: str, limit: int = 12, target: str | None = None) -> list[PanelSpec]:
        return suggest(self.profile, goal, self.data, limit=limit, target=target)


def scan(path: str | Path, sheet: str | None = None, apply_safe: bool = False) -> Scan:
    raw = load_table(path, sheet)
    prof = profile(raw)
    s = Scan(Path(path).expanduser().resolve(), sheet, raw, prof, suggest_cleaning(prof))
    s.apply([c for c in s.cleaning if c.safe] if apply_safe else [])
    return s


def scan_all(path: str | Path, apply_safe: bool = False) -> list[Scan]:
    """Every table under a path: each CSV, and each sheet of each Excel file."""
    scans = []
    for f in find_data_files(path):
        sheets = list_sheets(f) or [None]
        for sh in sheets:
            scans.append(scan(f, sh, apply_safe))
    return scans


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "figure"


def paginate(panels: list[PanelSpec], per_figure: int) -> list[list[PanelSpec]]:
    per_figure = max(per_figure, 1)
    return [panels[i : i + per_figure] for i in range(0, len(panels), per_figure)]


def auto_run(
    path: str | Path,
    goal: str = "explore",
    out_dir: str | Path = "vizdesk-output",
    layout: Layout | None = None,
    count: int = 8,
    apply_safe: bool = True,
    target: str | None = None,
) -> list[RenderResult]:
    """Scan every table under `path` and draw the top `count` suggestions for `goal`."""
    layout = layout or Layout()
    out = Path(out_dir).expanduser()
    results = []
    for s in scan_all(path, apply_safe):
        panels = s.suggestions(goal, limit=count, target=target)
        for page, chunk in enumerate(paginate(panels, layout.rows * layout.cols), start=1):
            spec = FigureSpec(
                source=str(s.source),
                sheet=s.sheet,
                cleaning=s.applied,
                panels=chunk,
                rows=layout.rows,
                cols=layout.cols,
                width=layout.width,
                height=layout.height,
                dpi=layout.dpi,
                padding=layout.padding,
                pad=layout.pad,
                theme=layout.theme,
                output=str(out / f"{_slug(s.name)}-{goal}-{page:02d}.{layout.fmt}"),
            )
            results.append(render_figure(s.data, spec))
    return results
