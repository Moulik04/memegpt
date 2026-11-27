"""
Builds the frontend's WOFF2 font subsets from the TTFs in backend/fonts, so
the site and the server-rendered Arc card use the same font sources.

Outputs go to frontend/src/app/fonts/ and are committed. Rerun only when a
source font, the character ranges or the weight range below change:

    python3 -m venv /tmp/fontvenv
    /tmp/fontvenv/bin/pip install fonttools==4.68.0 brotli==1.2.1
    /tmp/fontvenv/bin/python scripts/build_web_fonts.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "backend" / "fonts"
OUT = ROOT / "frontend" / "src" / "app" / "fonts"

# Google Fonts' own "latin" and "latin-ext" ranges.
LATIN = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,"
    "U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,"
    "U+FEFF,U+FFFD"
)
LATIN_EXT = (
    "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+1D00-1DBF,"
    "U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,"
    "U+2C60-2C7F,U+A720-A7FF"
)
FEATURES = "kern,liga,calt,ccmp,locl,mark,mkmk,tnum,lnum"

# Archivo sets the user's own words (names in a pasted chat), so it carries
# Latin Extended too. Anton sets only MemeGPT's own wordmark and headlines.
# Captions are drawn into the meme image by the backend.
ARCHIVO_WEIGHTS = (400, 800)


def _subset(source: Path, unicodes: str, out: Path) -> None:
    subset.main(
        [
            str(source),
            f"--unicodes={unicodes}",
            "--flavor=woff2",
            f"--layout-features={FEATURES}",
            f"--output-file={out}",
        ]
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archivo = TTFont(SOURCE / "Archivo-Variable.ttf")
        low, high = ARCHIVO_WEIGHTS
        pinned = Path(tmp) / "archivo-wght.ttf"
        instancer.instantiateVariableFont(archivo, {"wght": (low, high), "wdth": 100}).save(pinned)
        _subset(pinned, f"{LATIN},{LATIN_EXT}", OUT / "archivo.woff2")
    _subset(SOURCE / "Anton-Regular.ttf", LATIN, OUT / "anton.woff2")
    for license_file in ("OFL-Anton.txt", "OFL-Archivo.txt"):
        shutil.copyfile(SOURCE / license_file, OUT / license_file)
    for path in sorted(OUT.iterdir()):
        print(f"{path.stat().st_size:>8}  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
