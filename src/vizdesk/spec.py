"""Figure recipes.

A FigureSpec is everything needed to redraw one PNG: the source file and
sheet, the cleaning steps, the grid layout and one PanelSpec per chart. It is
saved next to the image as "<name>.vizdesk.json", so any figure can be
reopened, edited and redrawn later.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from vizdesk.cleaning import CleaningStep

SPEC_SUFFIX = ".vizdesk.json"
AGGREGATIONS = ["auto", "count", "sum", "mean", "median", "min", "max"]


@dataclass
class PanelSpec:
    chart: str
    x: str | None = None
    y: str | None = None
    hue: str | None = None  # colour / group column
    size: str | None = None  # bubble size column
    columns: list[str] = field(default_factory=list)  # multi-column charts (radar, heatmap, ...)
    agg: str = "auto"
    title: str = ""
    top_n: int = 15
    bins: int = 30
    log_y: bool = False
    options: dict = field(default_factory=dict)
    reason: str = ""  # why it was suggested; shown in the UI, not drawn

    def label(self) -> str:
        bits = [self.x, self.y, self.hue] + (self.columns[:3] if self.columns else [])
        cols = ", ".join(b for b in bits if b)
        return f"{self.chart}({cols})"

    @classmethod
    def from_dict(cls, d: dict) -> PanelSpec:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class FigureSpec:
    source: str
    sheet: str | None = None
    cleaning: list[CleaningStep] = field(default_factory=list)
    panels: list[PanelSpec] = field(default_factory=list)
    rows: int = 1
    cols: int = 1
    width: float = 8.0  # inches
    height: float = 6.0
    dpi: int = 150
    padding: bool = True
    pad: float = 0.3  # inches between panels when padding is on
    title: str = ""
    theme: str = "colorblind"
    output: str = "figure.png"

    @property
    def pixel_size(self) -> tuple[int, int]:
        return int(self.width * self.dpi), int(self.height * self.dpi)

    @property
    def spec_path(self) -> Path:
        return spec_path_for(self.output)

    def fit_grid(self) -> None:
        """Grow the grid when there are more panels than cells, keeping it close to square."""
        n = max(len(self.panels), 1)
        if self.rows * self.cols >= n:
            return
        self.cols = max(self.cols, math.ceil(math.sqrt(n)))
        self.rows = math.ceil(n / self.cols)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cleaning"] = [s.to_dict() for s in self.cleaning]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> FigureSpec:
        d = dict(d)
        d["cleaning"] = [CleaningStep.from_dict(s) for s in d.get("cleaning", [])]
        d["panels"] = [PanelSpec.from_dict(p) for p in d.get("panels", [])]
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def save(self) -> Path:
        path = self.spec_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
        return path


def parse_options(text: str) -> dict:
    """'filter=Name=AAPL; reversal=2%' -> {'filter': 'Name=AAPL', 'reversal': '2%'}."""
    out = {}
    for part in text.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            out[key.strip()] = value.strip()
    return out


def format_options(options: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in options.items() if k != "score")


def spec_path_for(image_path: str | Path) -> Path:
    p = Path(image_path)
    return p.with_name(p.stem + SPEC_SUFFIX)


def load_spec(path: str | Path) -> FigureSpec:
    """Accepts either the recipe file or the image it belongs to."""
    p = Path(path).expanduser()
    if not p.name.endswith(SPEC_SUFFIX):
        p = spec_path_for(p)
    return FigureSpec.from_dict(json.loads(p.read_text(encoding="utf-8")))


def find_specs(folder: str | Path) -> list[Path]:
    return sorted(Path(folder).expanduser().glob(f"*{SPEC_SUFFIX}"))
