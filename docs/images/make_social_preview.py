"""Build the 1280x640 GitHub social preview card.

GitHub crops the sides on some surfaces and shrinks it to a thumbnail on
others, so everything that must be readable stays well inside the frame and
nothing important is smaller than about 28 px tall.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import matplotlib.image as mpimg

ROOT = Path("/Users/mdrafsunsheikh/Projects/vizdesk")
# The project's own palette, read from docs/images/logo-dark.svg.
BG, PANEL, EDGE = "#0d1117", "#161b22", "#30363d"
TEXT, DIM = "#e6edf3", "#8b949e"
BLUE, ORANGE, LIGHT_BLUE, GREEN = "#006ba4", "#ff800e", "#5f9ed1", "#06d6a0"

W, H = 1280, 640
fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
fig.patch.set_facecolor(BG)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H)
ax.axis("off"); ax.invert_yaxis()

# A terminal window on the right, holding a real figure this tool produced.
win = FancyBboxPatch((700, 120), 520, 400, boxstyle="round,pad=0,rounding_size=12",
                     facecolor=PANEL, edgecolor=EDGE, linewidth=2)
ax.add_patch(win)
ax.add_patch(Rectangle((700, 120), 520, 34, facecolor="#21262d", edgecolor="none"))
for i, c in enumerate(["#ff6b6b", "#ffd166", "#06d6a0"]):
    ax.add_patch(plt.Circle((724 + i * 20, 137), 6, color=c))
ax.text(960, 137, "vizdesk", color=DIM, fontsize=10, ha="center", va="center",
        family="monospace")

img = mpimg.imread(ROOT / "docs/images/example-titanic-target.png")
ax.imshow(img, extent=(714, 1206, 510, 166), zorder=3)

# The name, the promise, and the one thing that makes it different.
ax.text(70, 196, "vizdesk", color=TEXT, fontsize=72, va="center",
        family="monospace", fontweight="bold")
ax.text(70, 268, "From spreadsheet", color=TEXT, fontsize=30, va="center")
ax.text(70, 310, "to clear charts.", color=TEXT, fontsize=30, va="center")

ax.text(70, 374, "Profiles your columns, suggests the cleaning,", color=DIM, fontsize=17, va="center")
ax.text(70, 404, "and picks the charts that answer your question.", color=DIM, fontsize=17, va="center")

# The counter-positioning, given its own badge because it is the hook.
badge = FancyBboxPatch((70, 448), 232, 46, boxstyle="round,pad=0,rounding_size=23",
                       facecolor=GREEN, edgecolor="none")
ax.add_patch(badge)
ax.text(186, 471, "No LLM inside", color="#06281f", fontsize=19, ha="center",
        va="center", fontweight="bold")
ax.text(318, 471, "offline  ·  same answer every time", color=DIM, fontsize=15, va="center")

# A quiet footer, so a thumbnail still says where to get it.
ax.text(70, 556, "uv tool install vizdesk", color=LIGHT_BLUE, fontsize=18, va="center",
        family="monospace")
ax.text(70, 590, "github.com/rafsunsheikh/vizdesk", color=DIM, fontsize=14, va="center",
        family="monospace")

# A thin accent stripe, picking up the palette used in the charts themselves.
for i, c in enumerate([BLUE, ORANGE, LIGHT_BLUE, "#c85200"]):
    ax.add_patch(Rectangle((0, 624 + 0), 320, 16, facecolor=c, edgecolor="none",
                           transform=ax.transData, zorder=1,
                           **{}) if False else Rectangle((i * 320, 624), 320, 16,
                                                         facecolor=c, edgecolor="none"))

out = ROOT / "docs/images/social-preview.png"
fig.savefig(out, facecolor=BG, dpi=100)
print(out)
