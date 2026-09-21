"""Fetch a portable FFmpeg build into ffmpeg/ (needed to bundle the exe).

Uses the imageio-ffmpeg wheel (a static gyan.dev build) so no manual
download is required:

    pip install imageio-ffmpeg
    python tools/fetch_ffmpeg.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = ROOT / "ffmpeg"
DEST = DEST_DIR / "ffmpeg.exe"


def main() -> int:
    try:
        import imageio_ffmpeg
    except ImportError:
        print("imageio-ffmpeg is not installed. Run: pip install imageio-ffmpeg")
        return 1
    DEST_DIR.mkdir(exist_ok=True)
    src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    shutil.copy2(src, DEST)
    print(f"ffmpeg -> {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
