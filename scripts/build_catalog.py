"""Build src/vizdesk/catalog/charts.json from the handbook's chart catalog markdown.

Usage:
    python scripts/build_catalog.py path/to/_chart_catalog_reference.md

The markdown uses one "## Category" heading per group and one "### Chart Name"
heading per chart, followed by "- **Field:** value" bullets.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "vizdesk" / "catalog" / "charts.json"

# Bullet labels in the markdown vary a little; map them onto one field name.
FIELD_MAP = {
    "description": "description",
    "data required": "data_required",
    "data requirements": "data_required",
    "data needed": "data_required",
    "data & parameters": "data_required",
    "use when": "use_when",
    "when to use": "use_when",
    "limitations": "limitations",
    "limitations & best practices": "limitations",
    "avoid when": "limitations",
    "trade-off": "limitations",
    "weaknesses": "limitations",
    "warning": "limitations",
    "similar charts": "similar",
    "tools": "tools",
    "best practice": "best_practice",
    "critical best practice": "best_practice",
    "critical rule": "best_practice",
    "critical note": "best_practice",
    "design guidelines": "best_practice",
    "variations": "variations",
    "also known as": "aliases",
}

STOP_SECTIONS = ("Quick Reference", "Tools Reference")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def split_name(heading: str) -> tuple[str, list[str]]:
    """'Radar Chart (Spider/Web/Polar/Star Chart)' -> ('Radar Chart', [...aliases])."""
    groups = re.findall(r"\(([^)]*)\)", heading)
    aliases = [a.strip() for g in groups for a in re.split(r"[/,]", g) if a.strip()]
    name = re.sub(r"\([^)]*\)", " ", heading)
    return re.sub(r"\s+", " ", name).strip(), aliases


def parse(md: str) -> list[dict]:
    charts: list[dict] = []
    category = ""
    current: dict | None = None
    last_field: str | None = None
    for line in md.splitlines():
        if line.startswith("## "):
            category = line[3:].strip()
            current = None
            if category.startswith(STOP_SECTIONS):
                break
            continue
        if line.startswith("### "):
            heading = line[4:].strip()
            if "see " in heading and "section" in heading:
                current = None  # cross reference, e.g. "Bullet Graph — see Comparisons"
                continue
            name, aliases = split_name(heading)
            current = {"key": slug(name), "name": name, "aliases": aliases, "category": category}
            charts.append(current)
            last_field = None
            continue
        if current is None:
            continue
        m = re.match(r"^- \*\*(.+?):\*\*\s*(.*)$", line)
        if m:
            label, value = m.group(1).strip().lower(), m.group(2).strip()
            field = FIELD_MAP.get(label, "notes")
            if field == "aliases":
                current["aliases"] += [a.strip() for a in value.split(",") if a.strip()]
            elif field in ("similar", "tools"):
                current[field] = [v.strip().rstrip(".") for v in value.split(",") if v.strip()]
            else:
                text = value if field != "notes" else f"{m.group(1).strip()}: {value}"
                current[field] = (current.get(field, "") + " " + text).strip()
            last_field = field
            continue
        sub = re.match(r"^\s+- (?:\*\*(.+?):\*\*\s*)?(.*)$", line)
        if sub and last_field:
            piece = f"{sub.group(1)}: {sub.group(2)}" if sub.group(1) else sub.group(2)
            current[last_field] = (str(current.get(last_field, "")) + " " + piece).strip()
    return charts


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    charts = parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
    OUT.write_text(json.dumps(charts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(charts)} charts to {OUT}")


if __name__ == "__main__":
    main()
