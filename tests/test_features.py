"""Script export, alt text, colorblind default and terminal preview."""

import io
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from vizdesk import preview
from vizdesk.pipeline import scan
from vizdesk.render import render_figure
from vizdesk.spec import FigureSpec, PanelSpec


def _figure(sales_csv, tmp_path, panels, **kw):
    s = scan(sales_csv, apply_safe=True)
    s.apply(s.cleaning)  # every cleaning step, so each one is exported as pandas code
    spec = FigureSpec(source=str(sales_csv), cleaning=s.applied, panels=panels, dpi=50,
                      output=str(tmp_path / "fig.png"), **kw)
    return s, render_figure(s.data, spec)


def test_colorblind_is_the_default_theme():
    assert FigureSpec(source="x").theme == "colorblind"


def test_exported_script_recreates_the_figure(sales_csv, tmp_path):
    panels = [PanelSpec("bar_chart", x="region", y="revenue"), PanelSpec("radar_chart", columns=["units", "revenue", "rating"]),
              PanelSpec("histogram", x="revenue_log"), PanelSpec("line_graph", x="order_date", y="revenue", options={"filter": "region=North"})]
    _, r = _figure(sales_csv, tmp_path, panels, rows=2, cols=2, title="Sales")
    script = r.script_path.read_text()
    assert "# %% Load the data" in script and "pd.read_csv" in script
    assert "pd.to_numeric(df['unit_price']" in script  # cleaning is plain pandas
    assert "drop_duplicates" in script and "np.log" in script
    first = r.path.read_bytes()
    r.path.unlink()
    done = subprocess.run([sys.executable, "-I", r.script_path.name], cwd=tmp_path, capture_output=True, text=True,
                          env={"MPLBACKEND": "Agg", "PATH": ""})
    assert done.returncode == 0, done.stderr
    again = Image.open(r.path)
    assert again.size == Image.open(io.BytesIO(first)).size


def test_alt_text_states_the_main_facts(sales_csv, tmp_path):
    panels = [PanelSpec("bar_chart", x="product", y="revenue"), PanelSpec("scatterplot", x="units", y="revenue"),
              PanelSpec("histogram", x="revenue"), PanelSpec("line_graph", x="order_date", y="revenue")]
    s, r = _figure(sales_csv, tmp_path, panels, rows=2, cols=2)
    assert r.alt_text.startswith("Figure with 4 charts in a 2 by 2 grid.")
    top = s.data.groupby("product")["revenue"].sum().idxmax()
    assert f"{top} is highest" in r.alt_text
    assert re.search(r"r = 0\.\d\d", r.alt_text)
    assert "right-skewed" in r.alt_text
    assert "monthly revenue" in r.alt_text
    assert r.alt_path.read_text().strip() == r.alt_text
    assert Image.open(r.path).text["Description"] == r.alt_text


def test_detect_protocol():
    assert preview.detect({"TERM": "xterm-kitty"}) == "kitty"
    assert preview.detect({"TERM_PROGRAM": "ghostty"}) == "kitty"
    assert preview.detect({"TERM_PROGRAM": "iTerm.app"}) == "iterm"
    assert preview.detect({"TERM_PROGRAM": "WezTerm"}) == "iterm"
    assert preview.detect({"TERM": "foot"}) == "sixel"
    assert preview.detect({"TERM": "xterm-kitty", "TMUX": "1"}) == "blocks"
    assert preview.detect({"TERM": "xterm-256color"}) == "blocks"
    assert preview.detect({"TERM": "xterm-kitty", "VIZDESK_PREVIEW": "sixel"}) == "sixel"


def _decode_sixel(data: str) -> np.ndarray:
    body = data[data.index("q") + 1 : data.rindex("\x1b\\")]
    w, h = map(int, re.match(r'"1;1;(\d+);(\d+)', body).groups())
    out = np.full((h, w), -1)
    tokens = re.findall(r'"[\d;]+|#\d+;2;\d+;\d+;\d+|#\d+|!\d+.|[?-~]|\$|-', body)
    color, x, top = 0, 0, 0
    for t in tokens:
        if t.startswith('"') or ";2;" in t:
            continue
        if t.startswith("#"):
            color = int(t[1:])
        elif t == "$":
            x = 0
        elif t == "-":
            x, top = 0, top + 6
        else:
            count, ch = (int(t[1:-1]), t[-1]) if t.startswith("!") else (1, t)
            bits = ord(ch) - 63
            for dx in range(count):
                for k in range(6):
                    if bits >> k & 1 and top + k < h:
                        out[top + k, x + dx] = color
            x += count
    return out


def test_sixel_round_trip():
    rng = np.random.default_rng(0)
    img = Image.fromarray(rng.integers(0, 255, (25, 37, 3), dtype=np.uint8))
    encoded = preview.sixel(img, colors=16)
    expected = np.array(img.convert("RGB").quantize(colors=16, method=Image.Quantize.MEDIANCUT))
    assert (_decode_sixel(encoded) == expected).all()


def test_kitty_and_iterm_payloads(tmp_path):
    img = Image.new("RGB", (300, 200), "white")
    k = preview.kitty(img, 40)
    chunks = re.findall(r"\x1b_G([^;]*);([^\x1b]*)\x1b\\", k)
    assert chunks[0][0].startswith("a=T,f=100,c=40")
    assert all(len(data) <= 4096 for _, data in chunks)
    assert chunks[-1][0].endswith("m=0") and all(c[0].endswith("m=1") for c in chunks[:-1])
    assert preview.iterm(img, 40).startswith("\x1b]1337;File=inline=1;")


def test_blocks_fit_the_terminal(tmp_path):
    path = tmp_path / "x.png"
    Image.new("RGB", (400, 300), (10, 20, 30)).save(path)
    rows = preview.block_rows(Image.open(path), 40, 10)
    assert len(rows) <= 10 and max(len(r) for r in rows) <= 40
    assert rows[0][0] == ((10, 20, 30), (10, 20, 30))
    text = preview.rich_blocks(path, 40, 10)
    assert "▀" in text.plain
