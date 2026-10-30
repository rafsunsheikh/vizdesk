"""Show PNG figures inside the terminal.

Protocols, best first:
  kitty   Kitty graphics protocol (Kitty, Ghostty, recent Konsole)
  iterm   iTerm2 inline images (iTerm2, WezTerm, VS Code with images enabled)
  sixel   Sixel graphics (foot, mlterm, Windows Terminal 1.22+, xterm -ti vt340)
  blocks  coloured half-block characters; works in any truecolour terminal, and inside the TUI

The protocol is picked from environment variables; VIZDESK_PREVIEW=kitty|iterm|sixel|blocks|none overrides it.
Inside tmux or screen the image protocols need passthrough, so blocks are used.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PROTOCOLS = ("kitty", "iterm", "sixel", "blocks", "none")


def detect(env: dict | None = None) -> str:
    env = dict(os.environ if env is None else env)
    forced = env.get("VIZDESK_PREVIEW", "").lower()
    if forced in PROTOCOLS:
        return forced
    term = env.get("TERM", "").lower()
    program = env.get("TERM_PROGRAM", "").lower()
    if env.get("TMUX") or term.startswith("screen") or term.startswith("tmux"):
        return "blocks"
    if env.get("KITTY_WINDOW_ID") or "kitty" in term or program == "ghostty" or "ghostty" in term:
        return "kitty"
    if program in ("iterm.app", "wezterm") or env.get("LC_TERMINAL", "").lower() == "iterm2":
        return "iterm"
    if env.get("WT_SESSION") or any(name in term for name in ("foot", "mlterm", "sixel", "contour")):
        return "sixel"
    return "blocks"


def _cells() -> tuple[int, int]:
    size = shutil.get_terminal_size((100, 30))
    return size.columns, size.lines


def _fit(image: Image.Image, max_w: int, max_h: int) -> Image.Image:
    scale = min(max_w / image.width, max_h / image.height, 1.0)
    return image.resize((max(int(image.width * scale), 1), max(int(image.height * scale), 1)), Image.LANCZOS)


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def kitty(image: Image.Image, columns: int) -> str:
    data = base64.standard_b64encode(_png_bytes(image)).decode()
    chunks = [data[i : i + 4096] for i in range(0, len(data), 4096)]
    out = []
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        head = f"a=T,f=100,c={columns}," if i == 0 else ""
        out.append(f"\x1b_G{head}m={more};{chunk}\x1b\\")
    return "".join(out) + "\n"


def iterm(image: Image.Image, columns: int) -> str:
    data = _png_bytes(image)
    return (f"\x1b]1337;File=inline=1;size={len(data)};width={columns};preserveAspectRatio=1:"
            f"{base64.b64encode(data).decode()}\a\n")


def sixel(image: Image.Image, colors: int = 64) -> str:
    """Encode an image as Sixel: 6-pixel-tall bands, one run-length coded pass per colour."""
    pal_img = image.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    palette = np.array(pal_img.getpalette()[: colors * 3]).reshape(-1, 3)
    px = np.array(pal_img)
    h, w = px.shape
    out = ['\x1bPq"1;1;%d;%d' % (w, h)]
    out += [f"#{i};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}" for i, (r, g, b) in enumerate(palette)]
    for top in range(0, h, 6):
        band = px[top : top + 6]
        weights = (1 << np.arange(band.shape[0]))[:, None]
        first = True
        for color in np.unique(band):
            bits = ((band == color) * weights).sum(axis=0)
            chars = (bits + 63).astype(np.uint8)
            # run-length encode: "!<count><char>" for repeats
            edges = np.flatnonzero(np.diff(chars)) + 1
            starts = np.concatenate(([0], edges))
            ends = np.concatenate((edges, [len(chars)]))
            runs = []
            for s, e in zip(starts, ends):
                ch = chr(chars[s])
                runs.append(f"!{e - s}{ch}" if e - s > 3 else ch * (e - s))
            out.append(("" if first else "$") + f"#{color}" + "".join(runs))
            first = False
        out.append("-")
    out.append("\x1b\\")
    return "".join(out) + "\n"


def block_rows(image: Image.Image, columns: int, rows: int) -> list[list[tuple[tuple[int, int, int], tuple[int, int, int]]]]:
    """Each cell is '▀': its foreground is the upper pixel, its background the lower one."""
    image = image.convert("RGB")
    scale = min(columns / image.width, rows * 2 / image.height)
    small = image.resize((max(int(image.width * scale), 1), max(int(image.height * scale) // 2 * 2, 2)), Image.LANCZOS)
    px = np.asarray(small)
    return [[(tuple(px[y, x]), tuple(px[y + 1, x])) for x in range(px.shape[1])] for y in range(0, px.shape[0] - 1, 2)]


def blocks(image: Image.Image, columns: int, rows: int) -> str:
    lines = []
    for row in block_rows(image, columns, rows):
        lines.append("".join(f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m▀" for a, b in row) + "\x1b[0m")
    return "\n".join(lines) + "\n"


def rich_blocks(path: str | Path, columns: int, rows: int):
    """The same half-block picture as a Rich Text, for showing inside Textual widgets."""
    from rich.text import Text

    text = Text()
    with Image.open(path) as image:
        for row in block_rows(image, columns, rows):
            for a, b in row:
                text.append("▀", style=f"rgb({a[0]},{a[1]},{a[2]}) on rgb({b[0]},{b[1]},{b[2]})")
            text.append("\n")
    return text


def show(path: str | Path, protocol: str | None = None, columns: int | None = None, stream=None) -> str:
    """Print an image to the terminal; returns the protocol used."""
    stream = stream or sys.stdout
    protocol = protocol or detect()
    if protocol == "none":
        return protocol
    cols, lines = _cells()
    columns = columns or min(cols, 160)
    with Image.open(path) as image:
        image.load()
        if protocol == "kitty":
            stream.write(kitty(image, columns))
        elif protocol == "iterm":
            stream.write(iterm(image, columns))
        elif protocol == "sixel":
            stream.write(sixel(_fit(image, columns * 10, max(lines - 4, 10) * 20)))
        else:
            stream.write(blocks(image, columns, max(lines - 4, 10)))
    stream.flush()
    return protocol
