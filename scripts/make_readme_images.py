"""Regenerate the README images in docs/images.

    python scripts/make_readme_images.py DATA_DIR

DATA_DIR holds CC0 (public domain) Kaggle files: titanic/Titanic-Dataset.csv,
housing/housing.csv and netflix/netflix_titles.csv. Download them with
`kaggle datasets download -d yasserh/titanic-dataset` (and camnugent/california-housing-prices,
shivamb/netflix-shows). Needs macOS `qlmanage` to turn the SVG screenshots into GIF frames.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from vizdesk.pipeline import Layout, auto_run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
SIZE = (150, 44)


async def screenshots(work: Path) -> list[Path]:
    """Walk through the TUI on the Titanic data and save one SVG per step."""
    from textual.widgets import Input, Select, SelectionList

    from vizdesk.tui.app import VizDeskApp

    shots = []
    app = VizDeskApp(path=str(work / "titanic.csv"), out_dir=str(work / "figures"))
    async with app.run_test(size=SIZE) as pilot:
        for _ in range(100):
            await pilot.pause(0.1)
            if app.suggestions:
                break

        async def snap(name: str, tab: str | None = None) -> None:
            if tab:
                app.action_tab(tab)
            await pilot.pause(0.6)
            path = OUT / f"tui-{name}.svg"
            app.save_screenshot(path.name, path=str(OUT))
            shots.append(path)

        await snap("data", "data")
        clean = app.query_one("#clean-list", SelectionList)
        clean.focus()
        await pilot.press("down", "down")
        await snap("clean", "clean")
        app.query_one("#goal", Select).value = "target"
        await pilot.pause(0.5)
        app.query_one("#suggest-list", SelectionList).focus()
        await pilot.press("down")
        await snap("suggest", "suggest")
        app.query_one("#suggest-add").press()
        await pilot.pause(0.5)
        app.query_one("#l-output", Input).value = str(work / "figures" / "titanic-target.png")
        await snap("compose")
        await pilot.press("ctrl+d")
        for _ in range(100):
            await pilot.pause(0.1)
            if getattr(app, "_preview_path", None):
                break
        await snap("preview", "preview")
        app.query_one("#catalog-search", Input).value = "flow"
        await pilot.pause(0.3)
        app.query_one("#catalog-list").highlighted = 0
        await snap("catalog", "catalog")
    return shots


def svg_to_png(svg: Path, work: Path) -> Path:
    subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(work), str(svg)], check=True, capture_output=True)
    return work / (svg.name + ".png")


def make_gif(svgs: list[Path], work: Path) -> Path:
    """Animated walkthrough: one frame per screenshot, cropped to the terminal window."""
    frames = []
    for svg in svgs:
        img = Image.open(svg_to_png(svg, work)).convert("RGB")
        bbox = Image.eval(img.convert("L"), lambda v: 255 if v < 250 else 0).getbbox()  # drop the white margin
        frames.append(img.crop(bbox).resize((1200, int(1200 * (bbox[3] - bbox[1]) / (bbox[2] - bbox[0])))))
    path = OUT / "vizdesk-demo.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=2200, loop=0, optimize=True)
    return path


def gallery(data: Path, work: Path) -> list[Path]:
    """Example output: what auto mode draws for three public datasets."""
    layout = Layout(rows=2, cols=3, width=16, height=9, dpi=80)
    made = []
    for name, src, goal in [("titanic-target", data / "titanic", "target"),
                            ("housing-explore", data / "housing", "explore"),
                            ("netflix-explore", data / "netflix", "explore")]:
        result = auto_run(src, goal, work / "gallery", layout, count=6)[0]
        target = OUT / f"example-{name}.png"
        shutil.copy(result.path, target)
        made.append(target)
    return made


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    data = Path(sys.argv[1]).expanduser()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copy(data / "titanic" / "Titanic-Dataset.csv", work / "titanic.csv")
        shots = asyncio.run(screenshots(work))
        print("wrote", make_gif(shots, work))
        for path in shots + gallery(data, work):
            print("wrote", path)


if __name__ == "__main__":
    main()
