# viidaa — clean, modern YouTube downloader (desktop)

![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![python](https://img.shields.io/badge/python-3.10%2B-green)
![license](https://img.shields.io/badge/license-MIT-orange)

A single-file Python desktop app (CustomTkinter + yt-dlp) with a dark
charcoal + dark-orange theme, download queue, pre-flight eligibility checks,
automatic client rotation around YouTube bot-checks, and bundled FFmpeg —
no installs, no PATH setup.

## Download (Windows)

Grab the latest from
[Releases](https://github.com/JonamMadeda/viidaa/releases):

- **`viidaa-Setup.exe`** — installer (per-user, no admin needed). Recommended.
- **`viidaa.exe`** — portable, just run it.

The app checks GitHub releases on launch and offers one-click updates.

## Run from source

```powershell
pip install -r requirements.txt
python tools/fetch_ffmpeg.py   # fetches portable FFmpeg into ffmpeg/
python viidaa.py
```

## Build the exe + installer

```powershell
pip install -r requirements.txt
python tools/fetch_ffmpeg.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name viidaa `
  --icon assets\viidaa.ico --add-data "assets;assets" --add-data "ffmpeg;ffmpeg" viidaa.py
& "C:\Program Files (x86)\NSIS\makensis.exe" installer\viidaa_setup.nsi
```

Outputs: `dist\viidaa.exe`, `installer\viidaa-Setup.exe`.

## Features

- MP4 / MP3, quality selector, download strategy rotation (Web → Android → iOS → TV)
- Pre-flight check: warns up front about private / DRM / upcoming / age-gated videos
- Queue with per-row progress, pause/resume, thumbnails, size estimates
- Cookies support (browser or `cookies.txt`) for bot-check bypass
- Bundled FFmpeg, system notifications, light/dark theme, persistent settings

## License

MIT — see [LICENSE](LICENSE).
