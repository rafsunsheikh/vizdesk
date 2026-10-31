"""Record a scripted vizdesk session to PNG frames, then to MP4 and GIF.

VHS would normally do this, but VHS needs ttyd and ttyd publishes no macOS
build, so this does the same job directly:

  * run the app in a pseudo-terminal of a fixed size, so the recording is the
    same every time rather than depending on the window someone happened to use
  * read what the app draws with pyte, a terminal emulator in Python, so we get
    the characters and their colours rather than a screen grab
  * draw each frame with Pillow and a real monospace font
  * hand the frames to ffmpeg

Usage:
    .venv-rec/bin/python docs/recording/record.py
"""
from __future__ import annotations

import os, pty, select, shutil, signal, subprocess, sys, time
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/recording/frames"
COLS, ROWS = 100, 30
FPS = 12
CELL_W, CELL_H = 11, 23          # measured for Menlo at the size below
FONT_SIZE = 18
PAD = 18
FONT_PATH = "/System/Library/Fonts/Menlo.ttc"

# The default colours when the app does not name one. Matches a dark terminal.
FG, BG = "e6edf3", "0d1117"

NAMED = {  # pyte reports the 8 base colours by name
    "black": "2e3436", "red": "ff6b6b", "green": "06d6a0", "brown": "ffd166",
    "yellow": "ffd166", "blue": "5f9ed1", "magenta": "c678dd", "cyan": "56b6c2",
    "white": "e6edf3", "default": None,
}


def colour(value: str, fallback: str) -> tuple[int, int, int]:
    if value in NAMED:
        value = NAMED[value] or fallback
    if len(value) != 6:
        value = fallback
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return tuple(int(fallback[i:i + 2], 16) for i in (0, 2, 4))


def render(screen: pyte.Screen, font, bold, path: Path) -> None:
    img = Image.new("RGB", (COLS * CELL_W + PAD * 2, ROWS * CELL_H + PAD * 2),
                    colour(BG, BG))
    d = ImageDraw.Draw(img)
    for y in range(ROWS):
        line = screen.buffer[y]
        for x in range(COLS):
            ch = line[x]
            if ch.bg != "default":
                d.rectangle([PAD + x * CELL_W, PAD + y * CELL_H,
                             PAD + (x + 1) * CELL_W, PAD + (y + 1) * CELL_H],
                            fill=colour(ch.bg, BG))
            if ch.data and ch.data != " ":
                d.text((PAD + x * CELL_W, PAD + y * CELL_H), ch.data,
                       font=bold if ch.bold else font,
                       fill=colour(ch.fg, FG))
    img.save(path)


def main() -> None:
    script = Path(__file__).with_name("session.py")
    # exec does not set __file__, and the session script needs it to find the
    # repository root.
    steps = {"__file__": str(script)}
    exec(compile(script.read_text(), str(script), "exec"), steps)
    ACTIONS = steps["ACTIONS"]
    CMD = steps["CMD"]

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE, index=0)
    bold = ImageFont.truetype(FONT_PATH, FONT_SIZE, index=1)

    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)

    pid, fd = pty.fork()
    if pid == 0:                       # child: become the app
        os.environ.update({"TERM": "xterm-256color", "COLORTERM": "truecolor",
                           "LINES": str(ROWS), "COLUMNS": str(COLS),
                           "PYTHONPATH": str(ROOT / "src")})
        os.chdir(str(ROOT / "docs/recording/workspace"))
        os.execv(CMD[0], CMD)
        os._exit(1)

    import fcntl, struct, termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    frame = 0
    def pump(seconds: float) -> None:
        """Let the app run for a while, drawing a frame every 1/FPS."""
        nonlocal frame
        end = time.monotonic() + seconds
        nxt = time.monotonic()
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], 0.02)
            if r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                stream.feed(data)
            now = time.monotonic()
            if now >= nxt:
                render(screen, font, bold, OUT / f"{frame:05d}.png")
                frame += 1
                nxt += 1 / FPS

    for action in ACTIONS:
        kind = action[0]
        if kind == "wait":
            pump(action[1])
        elif kind == "keys":
            os.write(fd, action[1].encode())
            pump(action[2] if len(action) > 2 else 0.6)
        elif kind == "type":           # one character at a time, like a person
            for c in action[1]:
                os.write(fd, c.encode())
                pump(0.06)
            pump(action[2] if len(action) > 2 else 0.4)

    os.kill(pid, signal.SIGTERM)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    os.close(fd)
    print(f"{frame} frames at {FPS} fps, {frame / FPS:.1f} seconds")


if __name__ == "__main__":
    main()
