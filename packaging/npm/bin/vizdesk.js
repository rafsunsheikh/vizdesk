#!/usr/bin/env node
// npm launcher for the vizdesk Python package.
//
// vizdesk is written in Python, so this script finds a way to run the
// matching Python version of it, in this order:
//   1. uv     ->  uvx --from vizdesk==<version> vizdesk ...
//   2. pipx   ->  pipx run --spec vizdesk==<version> vizdesk ...
//   3. python ->  a private virtual environment in ~/.cache/vizdesk/<version>,
//                 created once with pip and reused after that.
//
// Environment variables:
//   VIZDESK_PYTHON    python executable to use for option 3 (default: python3 / python)
//   VIZDESK_PIP_SPEC  what to pip install instead of vizdesk==<version> (e.g. a local path)
//   VIZDESK_LAUNCHER  force "uvx", "pipx" or "venv"

"use strict";

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const VERSION = require("../package.json").version;
const SPEC = process.env.VIZDESK_PIP_SPEC || `vizdesk==${VERSION}`;
const ARGS = process.argv.slice(2);
const IS_WIN = process.platform === "win32";

function has(cmd) {
  const probe = spawnSync(cmd, ["--version"], { stdio: "ignore", shell: IS_WIN });
  return probe.status === 0;
}

function run(cmd, args) {
  const result = spawnSync(cmd, args, { stdio: "inherit", shell: IS_WIN });
  if (result.error) {
    console.error(`vizdesk: could not start ${cmd}: ${result.error.message}`);
    process.exit(1);
  }
  process.exit(result.status === null ? 1 : result.status);
}

function findPython() {
  const candidates = process.env.VIZDESK_PYTHON ? [process.env.VIZDESK_PYTHON] : IS_WIN ? ["py", "python"] : ["python3", "python"];
  for (const py of candidates) {
    const ok = spawnSync(py, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"], { stdio: "ignore", shell: IS_WIN });
    if (ok.status === 0) return py;
  }
  return null;
}

function viaVenv() {
  const cacheRoot = process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
  const venv = path.join(cacheRoot, "vizdesk", VERSION);
  const exe = IS_WIN ? path.join(venv, "Scripts", "vizdesk.exe") : path.join(venv, "bin", "vizdesk");
  if (!fs.existsSync(exe)) {
    const py = findPython();
    if (!py) {
      console.error("vizdesk needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ " +
                    "or install uv (https://docs.astral.sh/uv/) and run this again.");
      process.exit(1);
    }
    console.error(`vizdesk: first run, installing ${SPEC} into ${venv} (one time only) ...`);
    fs.mkdirSync(path.dirname(venv), { recursive: true });
    for (const step of [
      [py, ["-m", "venv", venv]],
      [IS_WIN ? path.join(venv, "Scripts", "python.exe") : path.join(venv, "bin", "python"),
        ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", SPEC]],
    ]) {
      const r = spawnSync(step[0], step[1], { stdio: "inherit", shell: IS_WIN });
      if (r.status !== 0) {
        fs.rmSync(venv, { recursive: true, force: true });
        console.error("vizdesk: installation failed (see the messages above).");
        process.exit(1);
      }
    }
  }
  run(exe, ARGS);
}

const forced = process.env.VIZDESK_LAUNCHER;
if ((!forced || forced === "uvx") && has("uvx")) {
  run("uvx", ["--from", SPEC, "vizdesk", ...ARGS]);
} else if ((!forced || forced === "pipx") && has("pipx")) {
  run("pipx", ["run", "--spec", SPEC, "vizdesk", ...ARGS]);
} else {
  viaVenv();
}
