"""
viidaaz — Clean Modern YouTube Downloader (Desktop)
==================================================
Single-file desktop app built with CustomTkinter + yt-dlp.

Run:
    pip install customtkinter yt-dlp
    python viidaaz.py

FFmpeg (MP3 + best-quality MP4 merging) must be on PATH:
    Windows: winget install Gyan.FFmpeg
    macOS:   brew install ffmpeg
    Linux:   sudo apt install ffmpeg
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk
import yt_dlp


# ---------------------------------------------------------------------------
# Theme constants
# ---------------------------------------------------------------------------
BG_COLOR = "#1E1E1E"
FRAME_COLOR = "#2D2D2D"
FRAME_BORDER = "#3A3A3A"
ACCENT = "#E67E22"
ACCENT_HOVER = "#D35400"
ACCENT_TEXT = "#FFFFFF"
MUTED_TEXT = "#AAAAAA"
MAIN_TEXT = "#ECF0F1"

QUALITY_OPTIONS = ["Highest available", "1080p", "720p", "480p", "360p"]
FORMAT_OPTIONS = ["Video (MP4)", "Audio Only (MP3)"]
COOKIE_OPTIONS = ["Off", "Chrome", "Edge", "Firefox", "Brave", "cookies.txt file…"]
STRATEGY_OPTIONS = ["Auto (recommended)", "Web (best quality)",
                    "Android (bot-check bypass)", "iOS", "TV"]
# Mobile/TV clients reach YouTube through different endpoints — when the
# default web client is 429/bot-blocked, Android often still works
# (at reduced max quality, ~720p).
STRATEGY_CLIENTS = {
    "Auto (recommended)": ["web", "android", "ios", "tv"],
    "Web (best quality)": ["web"],
    "Android (bot-check bypass)": ["android"],
    "iOS": ["ios"],
    "TV": ["tv"],
}

APP_VERSION = "v2.5"

# Auto-update source: latest GitHub release + Setup asset below.
GITHUB_OWNER = "JonamMadeda"
GITHUB_REPO = "viidaaz"
UPDATE_ASSET = "viidaaz-Setup.exe"


def get_default_download_dir() -> str:
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return str(downloads)
    return os.getcwd()


def is_plausible_youtube_url(url: str) -> bool:
    if not url:
        return False
    pattern = re.compile(
        r"(https?://)?(www\.|m\.|music\.)?(youtube\.com/(watch|shorts|embed|live)|youtu\.be/)",
        re.IGNORECASE,
    )
    return bool(pattern.search(url.strip()))


def format_bytes(num) -> str:
    if not num:
        return "—"
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "—"
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def format_speed(bps) -> str:
    if not bps:
        return "—"
    return format_bytes(bps) + "/s"


def format_eta(seconds) -> str:
    if seconds is None:
        return "—"
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        return "—"
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def format_elapsed(start: float) -> str:
    s = int(time.time() - start) if start else 0
    m, s = divmod(max(s, 0), 60)
    if m < 60:
        return f"{m:02d}:{s:02d}"
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


def open_folder_in_os(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


class _YTLogger:
    """Forwards yt-dlp messages into the app log (thread-safe via after)."""

    def __init__(self, app):
        self._app = app

    def debug(self, msg: str):
        if not msg or msg.startswith("[debug"):
            return
        self._app._log_from_thread(msg)

    def warning(self, msg: str):
        self._app._log_from_thread(f"⚠ {msg}")

    def error(self, msg: str):
        self._app._log_from_thread(f"❌ {msg}")


def _section_title(parent, text: str):
    """Consistent small-caps section heading used across all cards."""
    lbl = ctk.CTkLabel(
        parent, text=text.upper(),
        font=ctk.CTkFont(size=11, weight="bold"),
        text_color=ACCENT,
    )
    return lbl


def _resource_path(rel: str) -> str:
    """Resolve a bundled resource (works in dev and in the PyInstaller exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _ffmpeg_exe() -> str | None:
    """Bundled FFmpeg first (ffmpeg/ffmpeg.exe), then system PATH."""
    bundled = _resource_path(os.path.join("ffmpeg", "ffmpeg.exe"))
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
# Palettes + persistent config (~/.config or %APPDATA%/viidaaz/config.json)
# ---------------------------------------------------------------------------
DARK_PALETTE = {
    "bg": "#1E1E1E", "card": "#2D2D2D", "border": "#3A3A3A", "field": "#1A1A1A",
    "footer": "#161616", "main": "#ECF0F1", "muted": "#AAAAAA",
    "faint": "#6E6E6E", "ghost": "#3A3A3A", "ghost_hover": "#4A4A4A",
    "danger_hover": "#5A2A2A", "accent": "#E67E22", "accent_hover": "#D35400",
    "logtext": "#CFCFCF", "placeholder": "#7A7A7A",
}
LIGHT_PALETTE = {
    "bg": "#ECEFF1", "card": "#FFFFFF", "border": "#D5D9DE", "field": "#F1F4F6",
    "footer": "#D8DEE4", "main": "#1F2733", "muted": "#5B6B7C",
    "faint": "#93A1B0", "ghost": "#D8DEE4", "ghost_hover": "#C6CFD7",
    "danger_hover": "#E3B3B3", "accent": "#D35400", "accent_hover": "#A04000",
    "logtext": "#33414F", "placeholder": "#93A1B0",
}

# option -> {known value (either palette): role}
_THEME_MAPS = {}
for _opt, _roles in {
    "fg_color": ["bg", "card", "field", "footer", "accent", "ghost"],
    "text_color": ["main", "muted", "faint", "logtext", "accent"],
    "hover_color": ["ghost_hover", "danger_hover", "accent_hover"],
    "border_color": ["border"],
    "placeholder_text_color": ["placeholder"],
    "button_color": ["accent"],
    "button_hover_color": ["accent_hover"],
    "progress_color": ["accent"],
    "scrollbar_button_color": ["ghost"],
    "scrollbar_button_hover_color": ["accent"],
}.items():
    _m = {}
    for _role in _roles:
        _m[DARK_PALETTE[_role]] = _role
        _m[LIGHT_PALETTE[_role]] = _role
    _THEME_MAPS[_opt] = _m


def _config_path() -> str | None:
    try:
        if sys.platform.startswith("win"):
            base = os.environ.get("APPDATA") or str(Path.home())
            folder = os.path.join(base, "viidaaz")
        else:
            folder = os.path.join(str(Path.home()), ".config", "viidaaz")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "config.json")
    except Exception:
        return None


def _load_config() -> dict:
    import json
    path = _config_path()
    if not path:
        return {}
    # One-time migration from the old "viidaa" config location.
    try:
        if not os.path.isfile(path):
            if sys.platform.startswith("win"):
                old = os.path.join(os.environ.get("APPDATA") or "", "viidaa",
                                   "config.json")
            else:
                old = os.path.join(str(Path.home()), ".config", "viidaa",
                                   "config.json")
            if old and os.path.isfile(old):
                shutil.copy2(old, path)
    except Exception:
        pass
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    import json
    path = _config_path()
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


class ViidaazApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._appearance = "Dark"  # or "Light"; applied after UI is built
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")
        self.title(f"viidaaz {APP_VERSION} — YouTube Downloader")
        self.minsize(980, 660)
        self.configure(fg_color=BG_COLOR)
        self._set_app_icon()
        self._guard_after_id = None
        self._guard_busy = False

        self.download_dir = get_default_download_dir()
        self.is_downloading = False
        self._cancel_event = threading.Event()
        self._download_start = 0.0
        self._last_progress_time = 0.0
        self._indeterminate = False
        self._timer_after_id = None
        self._pulse_after_id = None
        self._last_downloaded_file = None
        self._active_client = None  # winning YouTube client from pre-flight
        self._side_by_side = True
        self._resize_after_id = None
        # Queue state (feature: download queue)
        self.queue = []
        self.active_item = None
        self._pausing = False
        self._dl_phase = None
        self._thumb_cache = {}
        self._log_pristine = True
        self._last_error = ""
        self._save_after_id = None
        # Collapsible settings cards (rail always fits: collapse unused ones).
        # Only Output starts open — Destination/Cookies expand on demand and
        # the choice persists, so short viewports never clip content.
        self._card_bodies = {}
        self._card_chevs = {}
        self._card_state = {"output": True, "destination": False,
                            "cookies": False}

        # Root: header / content / footer
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_content()
        self._build_footer()
        self._init_config_and_theme()
        self._refresh_ffmpeg_badge()
        self._startup_checks()
        self._launch_fullscreen()
        self.bind("<Configure>", self._on_root_resize)
        # Blend the OS window chrome with the app background (Windows).
        self.after(300, self._dark_titlebar)
        # File-drop support (.url / text files carrying a link).
        self.after(800, self._hook_dropfiles)
        # Silent auto-update check shortly after launch.
        self.after(4000, lambda: threading.Thread(
            target=self._check_updates, args=(True,), daemon=True).start())

    # ------------------------------------------------------------------
    # OS title bar — immersive dark so it melts into the app background
    # ------------------------------------------------------------------
    def _dark_titlebar(self):
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
            # Root HWND first (GetParent of a toplevel is unreliable in Tk).
            hwnds = [self.winfo_id()]
            try:
                hwnds.append(user32.GetParent(self.winfo_id()))
            except Exception:
                pass
            for hwnd in [h for h in hwnds if h]:
                try:
                    use_dark = ctypes.c_int(1)
                    # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win 10 20H1+)
                    dwm.DwmSetWindowAttribute(
                        hwnd, 20, ctypes.byref(use_dark), ctypes.sizeof(use_dark))
                    try:
                        # Win 11+: paint caption + text to match the app.
                        bg = ctypes.c_int(0x001E1E1E)
                        dwm.DwmSetWindowAttribute(
                            hwnd, 35, ctypes.byref(bg), ctypes.sizeof(bg))
                        fg = ctypes.c_int(0x00ECF0F1)
                        dwm.DwmSetWindowAttribute(
                            hwnd, 36, ctypes.byref(fg), ctypes.sizeof(fg))
                    except Exception:
                        pass
                    break
                except Exception:
                    continue
        except Exception:
            pass

    # ------------------------------------------------------------------
    # App icon — custom dark-orange mark (taskbar / title bar)
    # ------------------------------------------------------------------
    def _set_app_icon(self):
        """Apply assets/viidaaz.ico + .png; silently keep defaults if missing."""
        self._icon_img = None
        try:
            ico = _resource_path(os.path.join("assets", "viidaaz.ico"))
            if os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                except Exception:
                    pass
            png = _resource_path(os.path.join("assets", "viidaaz.png"))
            if os.path.exists(png):
                try:
                    img = tk.PhotoImage(file=png)
                    self._icon_img = img  # keep a reference
                    self.iconphoto(True, img)
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Theme + persistent settings
    # ------------------------------------------------------------------
    def _pal(self) -> dict:
        return LIGHT_PALETTE if self._appearance == "Light" else DARK_PALETTE

    def _apply_theme(self, mode: str):
        """Recolor every widget by mapping known values through the palette."""
        pal = LIGHT_PALETTE if mode == "Light" else DARK_PALETTE
        try:
            self._walk_theme(self, pal)
        except Exception:
            pass
        try:
            ctk.set_appearance_mode(mode)
        except Exception:
            pass
        self._appearance = mode
        try:
            self.theme_btn.configure(text="☀" if mode == "Dark" else "🌙")
        except Exception:
            pass

    def _walk_theme(self, widget, pal: dict):
        try:
            children = widget.winfo_children()
        except Exception:
            return
        for ch in children:
            self._theme_widget(ch, pal)
            self._walk_theme(ch, pal)

    @staticmethod
    def _theme_widget(w, pal: dict):
        for opt, roles in _THEME_MAPS.items():
            try:
                cur = w.cget(opt)
            except Exception:
                continue
            if cur in roles:
                try:
                    w.configure(**{opt: pal[roles[cur]]})
                except Exception:
                    pass

    def toggle_theme(self):
        self._apply_theme("Light" if self._appearance == "Dark" else "Dark")
        self._schedule_config_save()

    def _init_config_and_theme(self):
        self._config = _load_config()
        mode = self._config.get("appearance", "Dark")
        if mode not in ("Dark", "Light"):
            mode = "Dark"
        self._apply_theme(mode)
        c = self._config
        if c.get("format") in FORMAT_OPTIONS:
            self.format_var.set(c["format"])
        if c.get("quality") in QUALITY_OPTIONS:
            self.quality_var.set(c["quality"])
        if c.get("strategy") in STRATEGY_OPTIONS:
            self.strategy_var.set(c["strategy"])
        if c.get("cookie_mode") in COOKIE_OPTIONS:
            self.cookie_var.set(c["cookie_mode"])
            cf = c.get("cookies_file")
            if (self.cookie_var.get() == COOKIE_OPTIONS[-1] and cf
                    and os.path.isfile(cf)):
                self.cookies_file = cf
        dd = c.get("download_dir")
        if dd and os.path.isdir(dd):
            self.download_dir = dd
            try:
                self.folder_label.configure(text=dd)
                self.footer_right.configure(text=dd)
            except Exception:
                pass
        saved_cards = c.get("cards")
        if isinstance(saved_cards, dict):
            for key in self._card_state:
                if isinstance(saved_cards.get(key), bool):
                    self._card_state[key] = saved_cards[key]
        self._paint_card_state()
        for var in (self.format_var, self.quality_var, self.strategy_var,
                    self.cookie_var):
            try:
                var.trace_add("write", lambda *_a: self._schedule_config_save())
            except Exception:
                pass

    def _schedule_config_save(self):
        if self._save_after_id:
            try:
                self.after_cancel(self._save_after_id)
            except Exception:
                pass
        try:
            self._save_after_id = self.after(400, self._save_now)
        except Exception:
            pass

    def _save_now(self):
        try:
            _save_config({
                "format": self.format_var.get(),
                "quality": self.quality_var.get(),
                "strategy": self.strategy_var.get(),
                "cookie_mode": self.cookie_var.get(),
                "cookies_file": self.cookies_file,
                "download_dir": self.download_dir,
                "appearance": self._appearance,
                "cards": dict(self._card_state),
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Fullscreen launch — fill the whole screen on startup
    # ------------------------------------------------------------------
    def _launch_fullscreen(self):
        """Maximize the window on all platforms (windowed, not kiosk)."""
        try:
            self.update_idletasks()
        except Exception:
            pass
        maximized = False
        if sys.platform.startswith("win") or sys.platform.startswith("linux"):
            try:
                self.state("zoomed")  # native maximize: fills screen, keeps chrome
                maximized = True
            except Exception:
                pass
        if not maximized:
            # macOS + fallback: size to the display
            try:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                self.geometry(f"{sw}x{sh - 50}+0+0")
            except Exception:
                self.geometry("1360x850")
        # Re-assert after the window manager settles (Windows needs this)
        self.after(80, self._reassert_maximized)

    def _reassert_maximized(self):
        if sys.platform.startswith("win") or sys.platform.startswith("linux"):
            try:
                if self.state() != "zoomed":
                    self.state("zoomed")
            except Exception:
                pass
        try:
            self.update_idletasks()
        except Exception:
            pass
        # The guardian verifies the result and fixes any overshoot.
        self._guard_window()

    def _display_workarea(self):
        """Visible work area of the monitor holding the window, in Tk units.

        Uses WinAPI on Windows because Tk's screen metrics go wrong under
        DPI virtualization / multi-monitor / RDP (window ends up bigger than
        the viewport with parts unreachable).
        """
        sw, sh, ox, oy = (self.winfo_screenwidth(), self.winfo_screenheight(),
                          0, 0)
        if sys.platform.startswith("win"):
            try:
                import ctypes
                scaling = float(self.tk.call("tk", "scaling")) or 1.0
                hwnd = self.winfo_id()
                hmon = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
                if not hmon:
                    hmon = ctypes.windll.user32.MonitorFromPoint(0, 0, 1)

                class _RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long),
                                ("top", ctypes.c_long),
                                ("right", ctypes.c_long),
                                ("bottom", ctypes.c_long)]

                class _MI(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong),
                                ("rcMonitor", _RECT), ("rcWork", _RECT),
                                ("dwFlags", ctypes.c_ulong)]

                mi = _MI()
                mi.cbSize = ctypes.sizeof(_MI)
                if ctypes.windll.user32.GetMonitorInfoW(hmon,
                                                        ctypes.byref(mi)):
                    w = mi.rcWork.right - mi.rcWork.left
                    h = mi.rcWork.bottom - mi.rcWork.top
                    if w > 0 and h > 0:
                        sw, sh = int(w / scaling), int(h / scaling)
                        ox = int(mi.rcWork.left / scaling)
                        oy = int(mi.rcWork.top / scaling)
            except Exception:
                pass
        return sw, sh, ox, oy

    # ------------------------------------------------------------------
    # Window guardian — fits the screen automatically, on any monitor,
    # after any maximize / restore / move / DPI change. Never fights a
    # fitting window; only corrects overflow or content clipping.
    # ------------------------------------------------------------------
    def _guard_window(self, _event=None):
        if self._guard_after_id:
            try:
                self.after_cancel(self._guard_after_id)
            except Exception:
                pass
        try:
            self._guard_after_id = self.after(250, self._guard_now)
        except Exception:
            pass

    def _content_need(self) -> tuple:
        """Minimum window (w, h) showing everything unclipped, measured live."""
        try:
            deck = self.command_card.winfo_reqheight()
            rail = self.controls_col.winfo_reqheight()
            prog = self.progress_card.winfo_reqheight()
        except Exception:
            return 980, 700
        zone2 = max(rail, prog + 140)  # 140px keeps the activity log useful
        return 980, 66 + 2 + deck + 10 + zone2 + 24 + 32

    def _guard_now(self):
        if self._guard_busy:
            return
        self._guard_busy = True
        try:
            sw, sh, ox, oy = self._display_workarea()
            need_w, need_h = self._content_need()
            want_w = min(max(need_w, 980), sw)
            want_h = min(max(need_h, 660), sh)
            w, h, x, y = (self.winfo_width(), self.winfo_height(),
                          self.winfo_x(), self.winfo_y())
            new_w, new_x = w, x
            if w < want_w and want_w <= sw:
                new_w = want_w
            elif w > sw:
                new_w, new_x = sw, ox
            elif x < ox - 32 or x > ox + sw - 120:
                new_x = ox
            new_h, new_y = h, y
            if h < want_h and want_h <= sh:
                new_h = want_h
                if y < oy or y > oy + sh - want_h:
                    new_y = oy
            elif h > sh:
                new_h, new_y = sh, oy
            elif y < oy - 32 or y > oy + sh - 120:
                new_y = oy
            if (new_w, new_h, new_x, new_y) != (w, h, x, y):
                try:
                    self.state("normal")
                except Exception:
                    pass
                try:
                    self.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
                except Exception:
                    pass
        finally:
            self._guard_busy = False

    # ------------------------------------------------------------------
    # Layout: header / two-pane content / footer
    # ------------------------------------------------------------------
    def _build_header(self):
        # Same charcoal as the app background — one continuous surface,
        # separated from content only by the orange rule below.
        bar = ctk.CTkFrame(self, fg_color=BG_COLOR, corner_radius=0, height=66)
        self.header_bar = bar
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=20)
        # In-header brand mark (same artwork as the window icon)
        try:
            from PIL import Image as _PILImage
            _png = _resource_path(os.path.join("assets", "viidaaz.png"))
            if os.path.exists(_png):
                _pil = _PILImage.open(_png).resize((36, 36))
                self._header_icon = ctk.CTkImage(
                    light_image=_pil, dark_image=_pil, size=(34, 34))
                ctk.CTkLabel(left, image=self._header_icon,
                             text="").grid(row=0, column=0, sticky="w",
                                           padx=(0, 10))
                _logo_col = 1
            else:
                _logo_col = 0
        except Exception:
            _logo_col = 0
        ctk.CTkLabel(
            left, text="viidaaz",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=ACCENT,
        ).grid(row=0, column=_logo_col, sticky="w")
        ctk.CTkLabel(
            left, text="Clean, fast YouTube downloads  •  MP4 & MP3",
            font=ctk.CTkFont(size=12), text_color=MUTED_TEXT,
        ).grid(row=0, column=_logo_col + 1, sticky="w", padx=(14, 0), pady=(6, 0))

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=20)
        self.theme_btn = ctk.CTkButton(
            right, text="🌙", width=38, height=30, corner_radius=8,
            fg_color="#1A1A1A", hover_color="#3A3A3A",
            text_color=MAIN_TEXT, font=ctk.CTkFont(size=14),
            command=self.toggle_theme,
        )
        self.theme_btn.grid(row=0, column=0, padx=(0, 10))
        self.ffmpeg_badge = ctk.CTkLabel(
            right, text="● FFmpeg", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=MUTED_TEXT, fg_color="#1A1A1A",
            corner_radius=8, width=110, height=30,
        )
        self.ffmpeg_badge.grid(row=0, column=1, padx=(0, 10))
        self.version_label = ctk.CTkLabel(
            right, text=APP_VERSION, font=ctk.CTkFont(size=12),
            text_color=MUTED_TEXT,
        )
        self.version_label.grid(row=0, column=2)
        # Click the version to check for updates (auto-checked at startup).
        try:
            self.version_label.configure(cursor="hand2")
            self.version_label.bind(
                "<Button-1>", lambda _e: self.check_updates_now())
        except Exception:
            pass

        ctk.CTkFrame(self, height=2, fg_color=ACCENT,
                     corner_radius=0).grid(row=0, column=0, sticky="sew")

    def _build_content(self):
        # Hierarchy: 1) command deck (always visible) 2) settings + monitor
        self.content = ctk.CTkFrame(self, fg_color=BG_COLOR)
        self.content.grid(row=1, column=0, sticky="nsew", padx=16, pady=12)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        # ---- Zone 1: command deck — link + primary action, never hidden ----
        self._build_command_card()

        # ---- Zone 2: settings rail + monitor ----
        self.split = ctk.CTkFrame(self.content, fg_color="transparent")
        self.split.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.split.grid_columnconfigure(1, weight=1)
        self.split.grid_rowconfigure(0, weight=1)

        # Settings rail — plain frame, no scrollbar: every card fits by
        # design (compact rhythm), nothing may hide behind a scroll.
        self.controls_col = ctk.CTkFrame(self.split, fg_color="transparent")
        self.controls_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.controls_col.grid_columnconfigure(0, weight=1)

        self._build_output_card()
        self._build_destination_card()
        self._build_cookies_card()

        self.monitor_col = ctk.CTkFrame(self.split, fg_color="transparent")
        self.monitor_col.grid(row=0, column=1, sticky="nsew")
        self.monitor_col.grid_columnconfigure(0, weight=1)
        self.monitor_col.grid_rowconfigure(2, weight=1)

        self._build_progress_card()
        self._build_queue_card()
        self._build_log_card()

        self._title_lookup_after_id = None

    def _card(self, parent, row: int):
        card = ctk.CTkFrame(parent, fg_color=FRAME_COLOR,
                            border_color=FRAME_BORDER, border_width=1,
                            corner_radius=14)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        card.grid_columnconfigure(0, weight=1)
        return card

    def _card_head(self, card, key: str, title_text: str):
        """Collapsible card header; returns the body frame for content rows."""
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        head.grid_columnconfigure(1, weight=1)
        chev = ctk.CTkButton(head, text="▾", width=30, height=26,
                             corner_radius=7, fg_color="transparent",
                             hover_color="#3A3A3A", text_color=MUTED_TEXT,
                             font=ctk.CTkFont(size=13),
                             command=lambda: self._toggle_card(key))
        chev.grid(row=0, column=0)
        _section_title(head, title_text).grid(row=0, column=1, sticky="w",
                                             padx=(4, 0))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew")
        body.grid_columnconfigure(0, weight=1)
        self._card_bodies[key] = body
        self._card_chevs[key] = chev
        return body

    def _toggle_card(self, key: str):
        self._card_state[key] = not self._card_state.get(key, True)
        self._paint_card_state(key)
        self._schedule_config_save()

    def _paint_card_state(self, key: str | None = None):
        keys = [key] if key else list(self._card_bodies)
        for k in keys:
            open_ = self._card_state.get(k, True)
            try:
                if open_:
                    self._card_bodies[k].grid()
                else:
                    self._card_bodies[k].grid_remove()
                self._card_chevs[k].configure(text="▾" if open_ else "▸")
            except Exception:
                pass

    def _build_command_card(self):
        """Zone 1: the primary task — link in, Download pressed. Always on top."""
        card = ctk.CTkFrame(self.content, fg_color=FRAME_COLOR,
                            border_color=ACCENT, border_width=1,
                            corner_radius=14)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        self.command_card = card
        _section_title(card, "Download").grid(
            row=0, column=0, sticky="w", padx=18, pady=(10, 6))

        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=14)
        bar.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            bar, placeholder_text="Paste YouTube link here...",
            height=48, corner_radius=10, fg_color="#1A1A1A",
            border_color=FRAME_BORDER, text_color=MAIN_TEXT,
            placeholder_text_color="#7A7A7A", font=ctk.CTkFont(size=14))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(bar, text="Paste", width=84, height=48,
                      corner_radius=10, fg_color="#3A3A3A",
                      hover_color="#4A4A4A", text_color=MAIN_TEXT,
                      command=self._paste_from_clipboard).grid(
            row=0, column=1, padx=(0, 8))
        self.download_btn = ctk.CTkButton(
            bar, text="⬇   Download", width=160, height=48, corner_radius=10,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=ACCENT_TEXT, command=self.start_download)
        self.download_btn.grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(bar, text="＋ Queue", width=100, height=48,
                      corner_radius=10, font=ctk.CTkFont(size=13),
                      fg_color="#3A3A3A", hover_color="#4A4A4A",
                      text_color=MAIN_TEXT,
                      command=self.enqueue_current).grid(
            row=0, column=3, padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(
            bar, text="Cancel", width=96, height=48, corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#3A3A3A", hover_color="#5A2A2A",
            text_color=MAIN_TEXT, state="disabled",
            command=self.cancel_download)
        self.cancel_btn.grid(row=0, column=4)

        # Live video-title preview sits with the link it describes
        self.title_label = ctk.CTkLabel(
            card, text="Paste a link to preview the video title here.",
            font=ctk.CTkFont(size=12), text_color=MUTED_TEXT,
            wraplength=900, justify="left", anchor="w")
        self.title_label.grid(row=2, column=0, sticky="ew",
                              padx=18, pady=(6, 10))
        self.url_entry.bind("<KeyRelease>",
                            lambda _e: self._schedule_title_lookup())
        # Keyboard flow: Enter downloads, Ctrl+V pastes, Esc cancels.
        self.url_entry.bind("<Return>", lambda _e: self.start_download())
        self.url_entry.bind("<Control-v>", self._paste_key)
        self.bind("<Escape>", lambda _e: self.cancel_download())

    def _build_output_card(self):
        card = self._card(self.controls_col, 0)
        body = self._card_head(card, "output", "①  Output")
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.grid(row=0, column=0, sticky="ew", padx=14, pady=(6, 8))
        grid.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(grid, text="Format", font=ctk.CTkFont(size=12),
                     text_color=MUTED_TEXT).grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(grid, text="Quality", font=ctk.CTkFont(size=12),
                     text_color=MUTED_TEXT).grid(
            row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 4))
        self.format_var = tk.StringVar(value=FORMAT_OPTIONS[0])
        self.quality_var = tk.StringVar(value=QUALITY_OPTIONS[0])
        ctk.CTkOptionMenu(grid, variable=self.format_var,
                          values=FORMAT_OPTIONS, height=38, corner_radius=10,
                          fg_color="#1A1A1A", button_color=ACCENT,
                          button_hover_color=ACCENT_HOVER,
                          text_color=MAIN_TEXT,
                          font=ctk.CTkFont(size=13)).grid(
            row=1, column=0, sticky="ew")
        ctk.CTkOptionMenu(grid, variable=self.quality_var,
                          values=QUALITY_OPTIONS, height=38, corner_radius=10,
                          fg_color="#1A1A1A", button_color=ACCENT,
                          button_hover_color=ACCENT_HOVER,
                          text_color=MAIN_TEXT,
                          font=ctk.CTkFont(size=13)).grid(
            row=1, column=1, sticky="ew", padx=(10, 0))
        # Download strategy: which YouTube client to request videos through.
        ctk.CTkLabel(body, text="Strategy", font=ctk.CTkFont(size=12),
                     text_color=MUTED_TEXT).grid(
            row=1, column=0, sticky="w", padx=18, pady=(6, 4))
        self.strategy_var = tk.StringVar(value=STRATEGY_OPTIONS[0])
        ctk.CTkOptionMenu(body, variable=self.strategy_var,
                          values=STRATEGY_OPTIONS, height=38, corner_radius=10,
                          fg_color="#1A1A1A", button_color=ACCENT,
                          button_hover_color=ACCENT_HOVER,
                          text_color=MAIN_TEXT,
                          font=ctk.CTkFont(size=13)).grid(
            row=2, column=0, sticky="ew", padx=14, pady=(0, 10))

    def _build_destination_card(self):
        card = self._card(self.controls_col, 1)
        body = self._card_head(card, "destination", "②  Destination")
        self.folder_label = ctk.CTkLabel(
            body, text=self.download_dir, anchor="w",
            font=ctk.CTkFont(size=12), text_color=MUTED_TEXT,
            fg_color="#1A1A1A", corner_radius=10, height=40,
            wraplength=330, justify="left")
        self.folder_label.grid(row=0, column=0, sticky="ew",
                               padx=14, ipadx=10)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=14, pady=(6, 10))
        row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(row, text="Browse…", height=36, corner_radius=9,
                      fg_color="#3A3A3A", hover_color="#4A4A4A",
                      text_color=MAIN_TEXT,
                      command=self.choose_folder).grid(
            row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(row, text="Open Folder", height=36, corner_radius=9,
                      fg_color="#3A3A3A", hover_color=ACCENT_HOVER,
                      text_color=MAIN_TEXT,
                      command=self.open_download_folder).grid(
            row=0, column=1, sticky="ew", padx=(5, 0))

    def _build_cookies_card(self):
        """③ Cookies — bot-check bypass lives with the other settings."""
        card = self._card(self.controls_col, 2)
        body = self._card_head(card, "cookies", "③  Cookies")
        ctk.CTkLabel(body, text="Fixes “Sign in to confirm you're not a bot”.",
                     font=ctk.CTkFont(size=11), text_color=MUTED_TEXT).grid(
            row=0, column=0, sticky="w", padx=18, pady=(6, 8))
        cookie_row = ctk.CTkFrame(body, fg_color="transparent")
        cookie_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        cookie_row.grid_columnconfigure(0, weight=1)
        self.cookie_var = tk.StringVar(value=COOKIE_OPTIONS[0])
        self.cookies_file = None
        ctk.CTkOptionMenu(cookie_row, variable=self.cookie_var,
                          values=COOKIE_OPTIONS, height=38, corner_radius=10,
                          fg_color="#1A1A1A", button_color=ACCENT,
                          button_hover_color=ACCENT_HOVER,
                          text_color=MAIN_TEXT,
                          font=ctk.CTkFont(size=13)).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(cookie_row, text="File…", width=76, height=38,
                      corner_radius=10, fg_color="#3A3A3A",
                      hover_color="#4A4A4A", text_color=MAIN_TEXT,
                      command=self.choose_cookies_file).grid(
            row=0, column=1)
        ctk.CTkLabel(body, text="Uses your own logged-in browser session. "
                                "Close the browser first.",
                     font=ctk.CTkFont(size=11), text_color="#6E6E6E").grid(
            row=2, column=0, sticky="w", padx=18, pady=(0, 12))

    def _build_progress_card(self):
        card = ctk.CTkFrame(self.monitor_col, fg_color=FRAME_COLOR,
                            border_color=FRAME_BORDER, border_width=1,
                            corner_radius=14)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        self.progress_card = card
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 4))
        head.grid_columnconfigure(0, weight=1)
        _section_title(head, "Status").grid(row=0, column=0, sticky="w")
        self.pause_btn = ctk.CTkButton(
            head, text="⏸ Pause", width=88, height=30, corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#3A3A3A", hover_color="#4A4A4A",
            text_color=MAIN_TEXT, state="disabled",
            command=self.toggle_pause)
        self.pause_btn.grid(row=0, column=1, padx=(0, 10))
        self.percent_label = ctk.CTkLabel(
            head, text="0%", font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT)
        self.percent_label.grid(row=0, column=2, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            card, height=16, corner_radius=8,
            fg_color="#1A1A1A", progress_color=ACCENT)
        self.progress_bar.grid(row=1, column=0, sticky="ew",
                               padx=18, pady=8)
        self.progress_bar.set(0)

        # Per-stage steps: Check → Download → Finish
        steps = ctk.CTkFrame(card, fg_color="transparent")
        steps.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 2))
        self.step_labels = []
        for i, name in enumerate(("① Check", "② Download", "③ Finish")):
            lbl = ctk.CTkLabel(steps, text=name,
                               font=ctk.CTkFont(size=12),
                               text_color=MUTED_TEXT)
            lbl.grid(row=0, column=i * 2, padx=(0, 4))
            self.step_labels.append(lbl)
            if i < 2:
                ctk.CTkLabel(steps, text="→", font=ctk.CTkFont(size=12),
                             text_color=MUTED_TEXT).grid(
                    row=0, column=i * 2 + 1, padx=(0, 4))
        self._set_step(-1)

        # Active-video meta: thumbnail + title / size (filled by pre-check)
        self.vmeta = ctk.CTkFrame(card, fg_color="transparent")
        self.vmeta.grid(row=3, column=0, sticky="ew", padx=18, pady=(4, 0))
        self.vmeta.grid_columnconfigure(1, weight=1)
        self.thumb_label = ctk.CTkLabel(self.vmeta, text="", width=112, height=63,
                                        fg_color="#1A1A1A", corner_radius=8)
        self.thumb_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.video_info_label = ctk.CTkLabel(
            self.vmeta, text="No video loaded yet.", anchor="w", justify="left",
            font=ctk.CTkFont(size=12), text_color=MUTED_TEXT,
            wraplength=560)
        self.video_info_label.grid(row=0, column=1, sticky="ew")
        # Hidden until a pre-check fills it — saves ~80px when idle.
        self.vmeta.grid_remove()

        meta = ctk.CTkFrame(card, fg_color="transparent")
        meta.grid(row=4, column=0, sticky="ew", padx=18, pady=(4, 2))
        meta.grid_columnconfigure(0, weight=1)
        self.stage_label = ctk.CTkLabel(
            meta, text="Stage: idle", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=MAIN_TEXT)
        self.stage_label.grid(row=0, column=0, sticky="w")
        self.elapsed_label = ctk.CTkLabel(
            meta, text="⏱ 00:00", anchor="e",
            font=ctk.CTkFont(size=13), text_color=MUTED_TEXT)
        self.elapsed_label.grid(row=0, column=1, sticky="e")
        self.status_label = ctk.CTkLabel(
            card, text="Ready — paste a link and hit Download.",
            font=ctk.CTkFont(size=12), text_color=MUTED_TEXT,
            wraplength=700, justify="left", anchor="w")
        self.status_label.grid(row=5, column=0, sticky="ew",
                               padx=18, pady=(0, 12))

    def _build_queue_card(self):
        """Download queue — batch links, they process one after another."""
        card = ctk.CTkFrame(self.monitor_col, fg_color=FRAME_COLOR,
                            border_color=FRAME_BORDER, border_width=1,
                            corner_radius=14)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        self.queue_card = card
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
        head.grid_columnconfigure(0, weight=1)
        self.queue_title = _section_title(head, "Queue (0)")
        self.queue_title.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text="Clear done", width=88, height=28,
                      corner_radius=8, fg_color="#3A3A3A",
                      hover_color="#4A4A4A", font=ctk.CTkFont(size=11),
                      command=self.clear_finished).grid(
            row=0, column=1, sticky="e")
        self.queue_list = ctk.CTkScrollableFrame(
            card, fg_color="transparent", height=96,
            scrollbar_button_color="#3A3A3A",
            scrollbar_button_hover_color=ACCENT)
        self.queue_list.grid(row=1, column=0, sticky="ew",
                             padx=12, pady=(0, 12))
        self.queue_list.grid_columnconfigure(0, weight=1)
        self.queue_empty = ctk.CTkLabel(
            self.queue_list, text="Queue is empty — ＋ Queue links to batch them.",
            font=ctk.CTkFont(size=11), text_color=MUTED_TEXT)
        self.queue_empty.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self._update_queue_visibility()

    # ------------------------------------------------------------------
    # Queue model — every download is an item with snapshotted settings
    # ------------------------------------------------------------------
    def _snapshot_item(self, url: str) -> dict:
        return {
            "id": time.time_ns(),
            "url": url,
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "strategy": self.strategy_var.get(),
            "cookie_mode": self.cookie_var.get(),
            "cookies_file": self.cookies_file,
            "title": None,
            "status": "queued",  # queued|active|paused|done|failed|cancelled
            "percent": "—",
            "error": None,
            "row": None,
        }

    def enqueue_current(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("No link", "Paste a YouTube link first.")
            return
        item = self._snapshot_item(url)
        self.queue.append(item)
        self._render_queue_row(item)
        self._refresh_queue_title()
        self.log(f"➕ Queued: {url}")
        self._process_queue()

    def _refresh_queue_title(self):
        try:
            self.queue_title.configure(text=f"QUEUE ({len(self.queue)})")
        except Exception:
            pass
        self._update_queue_visibility()

    def _update_queue_visibility(self):
        """Empty queue takes no space — the card hides itself entirely."""
        try:
            if self.queue:
                self.queue_card.grid()
            else:
                self.queue_card.grid_remove()
        except Exception:
            pass

    def _render_queue_row(self, item: dict):
        try:
            self.queue_empty.grid_forget()
        except Exception:
            pass
        pal = self._pal()
        row = ctk.CTkFrame(self.queue_list, fg_color="transparent")
        row.grid(row=len(self.queue_list.winfo_children()),
                 column=0, sticky="ew", pady=2)
        row.grid_columnconfigure(1, weight=1)
        dot = ctk.CTkLabel(row, text="●", width=20,
                           font=ctk.CTkFont(size=12),
                           text_color=pal["muted"])
        dot.grid(row=0, column=0)
        name = ctk.CTkLabel(row, text=self._short_url(item["url"]), anchor="w",
                            font=ctk.CTkFont(size=12), text_color=pal["main"])
        name.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        meta = ctk.CTkLabel(
            row, text=f"{self._short_opt(item['format'])} · {item['quality']}",
            font=ctk.CTkFont(size=11), text_color=pal["muted"])
        meta.grid(row=0, column=2, padx=(0, 8))
        pct = ctk.CTkLabel(row, text="—", width=52, anchor="e",
                           font=ctk.CTkFont(size=11, weight="bold"),
                           text_color=pal["accent"])
        pct.grid(row=0, column=3, padx=(0, 4))
        rm = ctk.CTkButton(row, text="✕", width=28, height=24, corner_radius=6,
                           fg_color="transparent", hover_color="#5A2A2A",
                           text_color=pal["muted"], font=ctk.CTkFont(size=11),
                           command=lambda: self._remove_queue_item(item))
        rm.grid(row=0, column=4)
        item["row"] = {"frame": row, "dot": dot, "name": name, "pct": pct}

    @staticmethod
    def _short_url(url: str, limit: int = 56) -> str:
        return url if len(url) <= limit else url[:limit] + "…"

    @staticmethod
    def _short_opt(format_label: str) -> str:
        return "MP3" if format_label.startswith("Audio") else "MP4"

    _ROW_COLORS = {"queued": "muted", "active": "accent", "paused": "accent",
                   "done": "done", "failed": "failed", "cancelled": "muted"}

    def _update_queue_row(self, item: dict):
        r = item.get("row")
        if not r:
            return
        pal = self._pal()
        colors = {"muted": pal["muted"], "accent": pal["accent"],
                  "done": "#2ECC71", "failed": "#E74C3C"}
        try:
            r["dot"].configure(
                text_color=colors[self._ROW_COLORS.get(item["status"], "muted")])
            if item["title"]:
                r["name"].configure(text=item["title"][:70])
            r["pct"].configure(text=item.get("percent", "—"))
        except Exception:
            pass

    def _remove_queue_item(self, item: dict):
        if item.get("status") == "active":
            messagebox.showinfo("Busy", "Cancel the download first.")
            return
        try:
            if item.get("row"):
                item["row"]["frame"].destroy()
        except Exception:
            pass
        if item in self.queue:
            self.queue.remove(item)
        if not self.queue:
            try:
                self.queue_empty.grid(row=0, column=0, sticky="w",
                                      padx=6, pady=4)
            except Exception:
                pass
        self._refresh_queue_title()

    def clear_finished(self):
        for item in [i for i in self.queue
                     if i["status"] in ("done", "failed", "cancelled")]:
            try:
                if item.get("row"):
                    item["row"]["frame"].destroy()
            except Exception:
                pass
            self.queue.remove(item)
        # re-stack remaining rows
        for idx, item in enumerate(self.queue):
            try:
                item["row"]["frame"].grid(row=idx, column=0, sticky="ew", pady=2)
            except Exception:
                pass
        if not self.queue:
            try:
                self.queue_empty.grid(row=0, column=0, sticky="w",
                                      padx=6, pady=4)
            except Exception:
                pass
        self._refresh_queue_title()

    def _process_queue(self):
        """Start the next queued item; settle to idle when the queue drains."""
        if self.active_item is not None:
            return
        nxt = next((i for i in self.queue if i["status"] == "queued"), None)
        if nxt is None:
            self._set_idle_ui()
            return
        self.active_item = nxt
        nxt["status"] = "active"
        self._update_queue_row(nxt)
        self._begin_item_ui(nxt)
        threading.Thread(target=self._preflight_and_download,
                         args=(nxt["url"], nxt), daemon=True).start()

    def _pending_count(self) -> int:
        return sum(1 for i in self.queue if i["status"] == "queued")

    def _after_item(self):
        """Advance the queue after an item finishes/fails/is cancelled."""
        self.active_item = None
        self._pausing = False
        self._dl_phase = None
        if self._pending_count():
            self._process_queue()
        else:
            self._set_idle_ui()

    def _set_idle_ui(self):
        self.is_downloading = False
        self._stop_timer()
        try:
            self.download_btn.configure(state="normal", text="⬇   Download")
            self.cancel_btn.configure(state="disabled")
            self.pause_btn.configure(state="disabled", text="⏸ Pause")
        except Exception:
            pass

    _LOG_HINT = ("👋 Paste a YouTube link above and hit Download.\n"
                 "Every step — checks, clients, speed, ETA — is narrated here.")

    def _build_log_card(self):
        card = ctk.CTkFrame(self.monitor_col, fg_color=FRAME_COLOR,
                            border_color=FRAME_BORDER, border_width=1,
                            corner_radius=14)
        card.grid(row=2, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
        head.grid_columnconfigure(0, weight=1)
        _section_title(head, "Activity").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text="Clear", width=76, height=28,
                      corner_radius=8, fg_color="#3A3A3A",
                      hover_color="#4A4A4A", font=ctk.CTkFont(size=11),
                      command=self._clear_log).grid(row=0, column=1, sticky="e")
        self.log_box = ctk.CTkTextbox(
            card, corner_radius=10, fg_color="#1A1A1A",
            border_color=FRAME_BORDER, border_width=1,
            text_color="#CFCFCF", font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew",
                          padx=18, pady=(0, 12))
        self.log_box.insert("end", self._LOG_HINT)
        self.log_box.configure(state="disabled")

    def _build_footer(self):
        foot = ctk.CTkFrame(self, fg_color="#161616", corner_radius=0, height=32)
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_columnconfigure(0, weight=1)
        foot.grid_propagate(False)
        self.footer_left = ctk.CTkLabel(
            foot, text="MP3 and 1080p+ MP4 merges need FFmpeg on your PATH.",
            font=ctk.CTkFont(size=11), text_color="#6E6E6E")
        self.footer_left.grid(row=0, column=0, sticky="w", padx=20)
        self.footer_right = ctk.CTkLabel(
            foot, text=self.download_dir, font=ctk.CTkFont(size=11),
            text_color="#6E6E6E")
        self.footer_right.grid(row=0, column=1, sticky="e", padx=20)

    def _refresh_ffmpeg_badge(self):
        found = _ffmpeg_exe() is not None
        try:
            self.ffmpeg_badge.configure(
                text="● FFmpeg OK" if found else "● No FFmpeg",
                text_color="#2ECC71" if found else "#E74C3C",
            )
        except Exception:
            pass

    def _startup_checks(self):
        """Log one-time environment hints (JS runtime for full formats)."""
        if shutil.which("deno") is None:
            self.after(500, lambda: self.log(
                "ℹ No Deno JS runtime found — some YouTube formats may be "
                "missing. Install it: winget install DenoLand.Deno"))
        exe = _ffmpeg_exe()
        if exe:
            self.after(600, lambda: self.log(f"ℹ FFmpeg ready: {exe}"))
        else:
            self.after(600, lambda: self.log(
                "⚠ No FFmpeg found — MP3 conversion and 1080p+ MP4 merging "
                "will fail. Reinstall viidaaz or add FFmpeg to PATH."))

    # ------------------------------------------------------------------
    # Responsive: stack panes on narrow windows, side-by-side when wide
    # ------------------------------------------------------------------
    def _on_root_resize(self, _event=None):
        if self._resize_after_id:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(150, self._apply_responsive)
        # Any user-driven maximize / restore / move re-runs the fit guardian.
        self._guard_window()

    def _apply_responsive(self):
        try:
            w = self.winfo_width()
        except Exception:
            return
        want_side = w >= 920
        if want_side == self._side_by_side:
            return
        self._side_by_side = want_side
        # detach both panes, then re-grid in the right arrangement
        try:
            self.controls_col.grid_forget()
            self.monitor_col.grid_forget()
        except Exception:
            pass
        if want_side:
            self.split.grid_columnconfigure(0, minsize=400)
            self.split.grid_columnconfigure(1, weight=1)
            self.split.grid_rowconfigure(0, weight=1)
            self.split.grid_rowconfigure(1, weight=0)
            self.controls_col.grid(row=0, column=0, sticky="nsew",
                                   padx=(0, 12), pady=0)
            self.monitor_col.grid(row=0, column=1, sticky="nsew")
        else:
            self.split.grid_columnconfigure(0, weight=1)
            self.split.grid_columnconfigure(1, weight=0)
            self.split.grid_rowconfigure(0, weight=0)
            self.split.grid_rowconfigure(1, weight=1)
            self.controls_col.grid(row=0, column=0, sticky="ew",
                                   padx=0, pady=(0, 12))
            self.monitor_col.grid(row=1, column=0, sticky="nsew")

    # ------------------------------------------------------------------
    # Logging (thread-safe)
    # ------------------------------------------------------------------
    def _log_from_thread(self, msg: str):
        self.after(0, lambda: self.log(msg))

    def log(self, msg: str):
        try:
            if self._log_pristine:
                self._log_pristine = False
                self.log_box.configure(state="normal")
                self.log_box.delete("1.0", "end")
                self.log_box.configure(state="disabled")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"[{ts}] {msg}\n")
            self.log_box.see("end")
            lines = self.log_box.get("1.0", "end").splitlines()
            if len(lines) > 400:
                self.log_box.delete("1.0", f"{len(lines) - 400}.0")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", self._LOG_HINT)
        self.log_box.configure(state="disabled")
        self._log_pristine = True

    # ------------------------------------------------------------------
    # Folder / clipboard / title preview
    # ------------------------------------------------------------------
    def choose_folder(self):
        selected = filedialog.askdirectory(initialdir=self.download_dir)
        if selected:
            self.download_dir = selected
            self.folder_label.configure(text=selected)
            try:
                self.footer_right.configure(text=selected)
            except Exception:
                pass
            self._schedule_config_save()

    def choose_cookies_file(self):
        """Pick an exported cookies.txt (e.g. via a 'Get cookies.txt' addon)."""
        path = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Cookies", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.cookies_file = path
            self.cookie_var.set(COOKIE_OPTIONS[-1])
            self.log(f"🍪 Using cookies file: {path}")
            self._schedule_config_save()

    def open_download_folder(self):
        try:
            os.makedirs(self.download_dir, exist_ok=True)
            open_folder_in_os(self.download_dir)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not open folder", f"{exc}")

    def _paste_from_clipboard(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return
        if text:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, text)
            self._schedule_title_lookup()

    def _paste_key(self, _event=None):
        self._paste_from_clipboard()
        return "break"  # suppress native paste (avoids double-insert)

    def _schedule_title_lookup(self):
        if self._title_lookup_after_id:
            self.after_cancel(self._title_lookup_after_id)
        self._title_lookup_after_id = self.after(700, self._lookup_title_threaded)

    def _lookup_title_threaded(self):
        url = self.url_entry.get().strip()
        if not is_plausible_youtube_url(url):
            return
        threading.Thread(target=self._fetch_title, args=(url,), daemon=True).start()

    def _fetch_title(self, url: str):
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
                info = ydl.extract_info(url, download=False)
            title = (info or {}).get("title", "").strip()
            duration = (info or {}).get("duration_string") or ""
            if title:
                text = f"🎬 {title}" + (f"  •  {duration}" if duration else "")
                self.after(0, lambda: self.title_label.configure(text=text))
        except Exception:  # noqa: BLE001, S110 — preview is best-effort
            pass

    # ------------------------------------------------------------------
    # Download flow — queue driven; one active item at a time
    # ------------------------------------------------------------------
    def start_download(self):
        """Primary action: download now if idle, otherwise queue the link."""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("No link", "Please paste a YouTube link first.")
            return
        if not is_plausible_youtube_url(url):
            if not messagebox.askyesno(
                "Unusual link",
                "This doesn't look like a YouTube URL.\nTry downloading anyway?",
            ):
                return
        item = self._snapshot_item(url)
        self.queue.append(item)
        self._render_queue_row(item)
        self._refresh_queue_title()
        if self.active_item is not None:
            self.log(f"➕ Queued (busy): {url}")
        self._process_queue()

    def _begin_item_ui(self, item: dict):
        url = item["url"]
        needs_ffmpeg = (
            item["format"].startswith("Audio")
            or item["quality"] in ("Highest available", "1080p")
        )
        if needs_ffmpeg and _ffmpeg_exe() is None:
            self.after(0, lambda: messagebox.showwarning(
                "FFmpeg not found",
                "FFmpeg wasn't found (no bundled copy, not on PATH).\n\n"
                "• MP3 conversion and best-quality MP4 merging need FFmpeg.\n"
                "• Reinstall viidaaz or add FFmpeg to your PATH, then try again.\n\n"
                "The download will still be attempted.",
            ))
        self.is_downloading = True
        self._cancel_event.clear()
        self._pausing = False
        self._dl_phase = "fetch"
        self._last_downloaded_file = None
        self._active_client = None
        self._download_start = time.time()
        self._last_progress_time = time.time()
        self._set_stage("Checking video…", indeterminate=True)
        self._set_step(0)
        self._clear_video_meta()
        self.download_btn.configure(state="disabled", text="Downloading…")
        self.cancel_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="⏸ Pause")
        self.progress_bar.set(0)
        self.percent_label.configure(text="—")
        self.status_label.configure(
            text="🔍 Checking if this video can be downloaded… (fast pre-check)")
        self.log(f"▶ Starting: {url}")
        self.log(f"Format={item['format']}  Quality={item['quality']}")
        self.log(f"Strategy={item['strategy']}  "
                 f"Cookies={self._cookie_summary(item)}  Folder={self.download_dir}")
        self._start_timer()

    def cancel_download(self):
        if self.active_item is None:
            return
        self._cancel_event.set()
        self.log("⏹ Cancel requested — stopping…")
        self._set_stage("Cancelling…", indeterminate=True)
        self.status_label.configure(text="Cancelling… finishing current step.")

    def toggle_pause(self):
        """Pause mid-download (keeps .part for resume) / resume it."""
        if self.active_item is None:
            return
        if self.active_item.get("status") == "paused":
            # Resume: straight back into the worker; .part file continues.
            self._pausing = False
            self._cancel_event.clear()
            self._dl_phase = "downloading"
            self.active_item["status"] = "active"
            self._update_queue_row(self.active_item)
            self.log("▶ Resuming…")
            self.pause_btn.configure(state="normal", text="⏸ Pause")
            self._set_stage("Downloading…", indeterminate=False)
            self._start_timer()
            threading.Thread(
                target=self._download_worker,
                args=(self.active_item["url"], self.active_item),
                daemon=True).start()
        elif self._dl_phase == "downloading":
            self._pausing = True
            self._cancel_event.set()
            self.log("⏸ Pausing…")

    def _set_step(self, active: int):
        """Stage chips: 0 Check, 1 Download, 2 Finish; -1 reset; 3 all done."""
        try:
            pal = self._pal()
            for i, lbl in enumerate(self.step_labels):
                if active == 3 or i < active:
                    lbl.configure(text_color="#2ECC71",
                                  font=ctk.CTkFont(size=12, weight="bold"))
                elif i == active:
                    lbl.configure(text_color=pal["accent"],
                                  font=ctk.CTkFont(size=12, weight="bold"))
                else:
                    lbl.configure(text_color=pal["muted"],
                                  font=ctk.CTkFont(size=12))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Pre-flight check — verdict BEFORE downloading, never after waiting
    # ------------------------------------------------------------------
    def _ask_from_thread(self, title: str, message: str) -> bool:
        """Yes/No dialog callable from a worker thread; blocks for the answer."""
        result = {}
        done = threading.Event()

        def _show():
            try:
                result["value"] = messagebox.askyesno(title, message)
            finally:
                done.set()

        self.after(0, _show)
        done.wait()
        return bool(result.get("value", False))

    def _preflight_and_download(self, url: str, item: dict):
        """Step 1: metadata check, rotating YouTube clients until one works.
        Step 2: download with the winning client, only if the video is viable."""
        clients = STRATEGY_CLIENTS.get(item.get("strategy"),
                                       STRATEGY_CLIENTS[STRATEGY_OPTIONS[0]])
        info = None
        last_error = None
        for client in clients:
            if self._cancel_event.is_set():
                self.after(0, self._cancelled)
                return
            self._log_from_thread(
                f"🔍 Pre-check: trying {client.upper()} client…")
            try:
                check_opts = {
                    "quiet": False,
                    "no_warnings": False,
                    "noplaylist": True,
                    "socket_timeout": 20,
                    "retries": 2,
                    "logger": _YTLogger(self),
                    "extractor_args": {"youtube": {"player_client": [client]}},
                }
                self._apply_cookies(check_opts, item)
                with yt_dlp.YoutubeDL(check_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadCancelled:
                self.after(0, self._cancelled)
                return
            except Exception as exc:  # noqa: BLE001 — bot-check, 429, bad URL…
                last_error = str(exc)
                self._log_from_thread(
                    f"   ✗ {client.upper()}: {self._short_reason(last_error)}")
                continue
            if info:
                self._active_client = client
                self._log_from_thread(f"   ✓ {client.upper()} client worked.")
                if client in ("android", "ios"):
                    self._log_from_thread(
                        "   ℹ Mobile clients cap quality around 720p.")
                break

        if self._cancel_event.is_set():
            self.after(0, self._cancelled)
            return

        # Every client failed → a download will very likely fail too.
        if not info:
            msg = last_error or "YouTube returned no video info."
            self._log_from_thread(f"⛔ Pre-check failed on all clients: {msg[:200]}")
            go = self._ask_from_thread(
                "Video check failed",
                "viidaaz couldn't read this video's info through any client "
                f"({', '.join(c.upper() for c in clients)}), so downloading "
                "will very likely fail too.\n\n"
                f"Reason: {self._short_reason(msg)}\n\n"
                "Try downloading anyway?")
            if not go or self._cancel_event.is_set():
                self.after(0, lambda: self._abort_before_download(
                    "⛔ Pre-check failed — download not started. See Activity."))
                return
            self._log_from_thread("↪ Continuing anyway (your choice).")
            self._download_worker(url, item)
            return

        level, summary, issues = self._assess_info(info)
        title = (info.get("title") or "Unknown title").strip()
        item["title"] = title
        self.after(0, lambda: self._update_queue_row(item))
        self._log_from_thread(f"🔍 Pre-check: {summary}")
        for issue in issues:
            self._log_from_thread(f"   • {issue}")

        if level == "block":
            go = self._ask_from_thread(
                "Likely not downloadable",
                f"“{title}”\n\nThis video looks NOT downloadable:\n"
                + "\n".join(f"• {i}" for i in issues)
                + "\n\nTry anyway?")
            if not go or self._cancel_event.is_set():
                self.after(0, lambda: self._abort_before_download(
                    "⛔ Not started — video looks undownloadable (see Activity)."))
                return
            self._log_from_thread("↪ Continuing anyway (your choice).")
        elif level == "warn":
            go = self._ask_from_thread(
                "Heads up before downloading",
                f"“{title}”\n\n{summary}\n"
                + "\n".join(f"• {i}" for i in issues)
                + "\n\nDownload anyway?")
            if not go or self._cancel_event.is_set():
                self.after(0, lambda: self._abort_before_download(
                    "⏹ Cancelled before downloading."))
                return
        else:
            self._log_from_thread("✔ Looks good — starting download…")
            self.after(0, lambda: self._set_stage(
                "Downloading…", indeterminate=True))
        # Publish thumbnail + size estimate, then download with this item.
        try:
            size = self._estimate_size(
                info, item.get("quality"), item.get("format", "").startswith("Audio"))
            if size:
                self._log_from_thread(f"ℹ Estimated size: ≈ {format_bytes(size)}")
            self._fetch_thumbnail(info)
            self.after(0, lambda: self._show_video_meta(info, size))
        except Exception:
            pass
        self._download_worker(url, item)

    @staticmethod
    def _assess_info(info: dict) -> tuple:
        """Return (level, summary, issues); level is ok | warn | block."""
        issues = []
        title = (info.get("title") or "Unknown").strip()
        live = info.get("live_status")
        if live == "is_upcoming":
            issues.append("It's an upcoming premiere/stream — not out yet.")
            return "block", f"{title}: not released yet.", issues
        if live == "is_live":
            issues.append("It's a LIVE stream — downloads run in real time, "
                          "only at stream quality.")
        formats = info.get("formats") or []
        if not formats:
            issues.append("YouTube exposed no downloadable formats.")
            return "block", f"{title}: no formats.", issues
        if any(f.get("has_drm") for f in formats):
            issues.append("DRM-protected — no downloader can save it.")
            return "block", f"{title}: DRM protected.", issues
        avail = (info.get("availability") or "").lower()
        if avail == "private":
            issues.append("Marked private.")
            return "block", f"{title}: private.", issues
        if avail in ("premium_only", "subscriber_only",
                     "needs_auth", "needs_subscription"):
            issues.append(f"Needs a paid/logged-in account ({avail}).")
            return "block", f"{title}: account required.", issues
        if avail == "unavailable":
            issues.append("Marked unavailable (region-block or removed).")
            return "block", f"{title}: unavailable.", issues
        if info.get("age_limit"):
            issues.append(f"Age-restricted ({info.get('age_limit')}+) — needs "
                          "YouTube cookies or it will fail.")
        try:
            dur = int(info.get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0
        if dur >= 7200:
            issues.append(f"Very long ({dur // 3600}h {(dur % 3600) // 60:02d}m) "
                          "— big file, slow merge.")
        if live == "is_live":
            return "warn", f"{title}: live stream.", issues
        if issues:
            return "warn", f"{title}: needs attention.", issues
        dur_s = info.get("duration_string") or ""
        return "ok", f"{title}" + (f" ({dur_s})" if dur_s else ""), issues

    @staticmethod
    def _short_reason(raw: str) -> str:
        low = raw.lower()
        if "not a bot" in low or "sign in to confirm" in low:
            return ("YouTube bot-check on this network "
                    "(add cookies or switch network).")
        if "429" in low or "too many requests" in low:
            return "Rate-limited by YouTube (HTTP 429) — wait / switch network."
        if "private" in low:
            return "Video is private."
        if "unsupported url" in low:
            return "Link not recognized."
        return raw[:160]

    def _abort_before_download(self, msg: str):
        self.log(msg)
        self._finish_active("cancelled")
        # Only paint idle state when the queue truly drained — otherwise the
        # next item already started and owns the status UI.
        if self.active_item is None:
            self._set_stage_text("Idle")
            self._set_step(-1)
            self.percent_label.configure(text="—")
            self.status_label.configure(text=msg)

    def _cookie_summary(self, item: dict | None = None) -> str:
        mode = (item or {}).get("cookie_mode", self.cookie_var.get())
        if mode == COOKIE_OPTIONS[-1]:
            cf = (item or {}).get("cookies_file", self.cookies_file)
            return cf or "cookies.txt (no file chosen)"
        return mode

    def _apply_cookies(self, opts: dict, item: dict | None = None) -> None:
        """Attach browser/file cookies so YouTube drops the bot-check."""
        mode = (item or {}).get("cookie_mode", self.cookie_var.get())
        if mode in ("Chrome", "Edge", "Firefox", "Brave"):
            # (browser, profile=None, keyring=None, container=None)
            opts["cookiesfrombrowser"] = (mode.lower(), None, None, None)
        elif mode == COOKIE_OPTIONS[-1]:
            cf = (item or {}).get("cookies_file", self.cookies_file)
            if cf:
                opts["cookiefile"] = cf

    def _build_ydl_opts(self, item: dict | None = None,
                        format_override: str | None = None) -> dict:
        fmt_label = (item or {}).get("format", self.format_var.get())
        is_audio = fmt_label.startswith("Audio")
        quality = (item or {}).get("quality", self.quality_var.get())
        height_map = {"Highest available": None, "1080p": 1080,
                      "720p": 720, "480p": 480, "360p": 360}
        max_h = height_map.get(quality)

        if format_override:
            ydl_format = format_override
        elif is_audio:
            ydl_format = "bestaudio/best"
        elif max_h is None:
            ydl_format = "bestvideo+bestaudio/best"
        else:
            ydl_format = (f"bestvideo[height<={max_h}]+bestaudio/"
                          f"best[height<={max_h}]/best")

        opts = {
            "format": ydl_format,
            "outtmpl": os.path.join(self.download_dir,
                                    "%(title)s [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "restrict_filenames": False,
            "windowsfilenames": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "progress_with_newline": False,
            "logger": _YTLogger(self),
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            # Download through the client that survived pre-flight.
            **({"extractor_args": {"youtube": {"player_client": [client]}}}
               if (client := self._active_client) else {}),
            # Point yt-dlp at the bundled FFmpeg (falls back to PATH).
            **({"ffmpeg_location": _exe} if (_exe := _ffmpeg_exe()) else {}),
            **({"postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"}]}
               if is_audio else {"merge_output_format": "mp4"}),
        }
        self._apply_cookies(opts, item)
        return opts

    @staticmethod
    def _looks_like_format_problem(msg: str) -> bool:
        low = msg.lower()
        return any(s in low for s in (
            "requested format is not available",
            "no video formats found",
            "no formats found",
            "incompatible",
        ))

    def _download_worker(self, url: str, item: dict):
        try:
            os.makedirs(self.download_dir, exist_ok=True)
            try:
                with yt_dlp.YoutubeDL(self._build_ydl_opts(item)) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as first_exc:
                # One automatic retry with the most permissive format —
                # fixes "format not available at this quality" failures.
                if (not self._cancel_event.is_set()
                        and self._looks_like_format_problem(str(first_exc))):
                    self._log_from_thread(
                        "↻ Chosen quality unavailable — retrying with "
                        "best available format…")
                    with yt_dlp.YoutubeDL(
                            self._build_ydl_opts(
                                item, "best/bestvideo+bestaudio")) as ydl:
                        ydl.download([url])
                else:
                    raise
        except yt_dlp.utils.DownloadCancelled:
            if self._pausing:
                self.after(0, self._paused)
            else:
                self.after(0, self._cancelled)
        except yt_dlp.utils.DownloadError as exc:
            self.after(0, lambda: self._fail(str(exc)))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._fail(f"Unexpected error: {exc}"))
        else:
            if self._cancel_event.is_set():
                self.after(0, self._cancelled)
            else:
                self.after(0, self._succeed)

    # -- hooks (run on worker thread) -----------------------------------
    def _progress_hook(self, d: dict):
        if self._cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0) or 0
            frag_idx = d.get("fragment_index")
            frag_count = d.get("fragment_count")
            if not total and frag_idx and frag_count:
                frac = frag_idx / max(frag_count, 1)
                total_str = f"fragment {frag_idx}/{frag_count}"
            elif total:
                frac = downloaded / total if total else 0
                total_str = f"{format_bytes(downloaded)} / {format_bytes(total)}"
            else:
                frac = 0
                total_str = f"{format_bytes(downloaded)} downloaded"
            percent = f"{frac * 100:.1f}%" if (total or frag_idx) else "…"
            info = (f"{total_str}  •  {format_speed(d.get('speed'))}  •  "
                    f"ETA {format_eta(d.get('eta'))}")
            filename = os.path.basename(d.get("filename") or "")
            self.after(0, lambda: self._on_downloading(
                frac, percent, info, filename))
        elif status == "finished":
            fn = d.get("filename", "")
            if fn:
                self._last_downloaded_file = fn
            self.after(0, lambda: self._on_finished_file(fn))

    def _postprocessor_hook(self, d: dict):
        if self._cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        status = d.get("status")
        info = d.get("info_dict") or {}
        title = info.get("title") or ""
        if status == "started":
            pp = d.get("postprocessor") or "Post-processing"
            self.after(0, lambda: self._on_postproc_started(pp, title))
        elif status == "finished":
            self.after(0, lambda: self._on_postproc_finished())

    # -- UI updates (main thread only) -----------------------------------
    def _set_stage(self, text: str, indeterminate: bool = False):
        self.stage_label.configure(text=f"Stage: {text}")
        self._indeterminate = indeterminate
        if indeterminate:
            self._pulse_indeterminate()
        else:
            if self._pulse_after_id:
                try:
                    self.after_cancel(self._pulse_after_id)
                except Exception:
                    pass
                self._pulse_after_id = None

    def _pulse_indeterminate(self):
        if not self._indeterminate or not self.is_downloading:
            return
        import math
        val = 0.15 + 0.7 * abs(math.sin(time.time() * 1.4))
        try:
            self.progress_bar.set(val)
        except Exception:
            pass
        self._pulse_after_id = self.after(100, self._pulse_indeterminate)

    def _start_timer(self):
        self._tick_timer()

    def _tick_timer(self):
        if not self.is_downloading:
            return
        try:
            self.elapsed_label.configure(
                text=f"⏱ {format_elapsed(self._download_start)}")
            idle = time.time() - self._last_progress_time
            if idle > 8 and self._indeterminate:
                self.status_label.configure(
                    text=(f"Still working… {int(idle)}s since last update. "
                          "Large videos / slow networks can take minutes. "
                          "See Activity log."))
        except Exception:
            pass
        self._timer_after_id = self.after(500, self._tick_timer)

    def _stop_timer(self):
        if self._timer_after_id:
            try:
                self.after_cancel(self._timer_after_id)
            except Exception:
                pass
            self._timer_after_id = None
        if self._pulse_after_id:
            try:
                self.after_cancel(self._pulse_after_id)
            except Exception:
                pass
            self._pulse_after_id = None
        self._indeterminate = False

    def _on_downloading(self, frac, percent, info, filename):
        self._last_progress_time = time.time()
        self._dl_phase = "downloading"
        if self._indeterminate:
            self._indeterminate = False
            if self._pulse_after_id:
                try:
                    self.after_cancel(self._pulse_after_id)
                except Exception:
                    pass
                self._pulse_after_id = None
        self._set_stage_text("Downloading…")
        self._set_step(1)
        try:
            self.pause_btn.configure(state="normal", text="⏸ Pause")
        except Exception:
            pass
        frac = max(0.0, min(1.0, frac)) if frac else 0
        self.progress_bar.set(frac)
        self.percent_label.configure(text=percent)
        if self.active_item is not None:
            self.active_item["percent"] = percent
            self._update_queue_row(self.active_item)
        short = (filename[:60] + "…") if len(filename) > 60 else filename
        self.status_label.configure(text=f"{info}" + (f"\n{short}" if short else ""))

    def _set_stage_text(self, text: str):
        try:
            self.stage_label.configure(text=f"Stage: {text}")
        except Exception:
            pass

    def _on_finished_file(self, filename: str):
        self._last_progress_time = time.time()
        self._dl_phase = "post"  # pause no longer safe: output may be complete
        try:
            self.pause_btn.configure(state="disabled")
        except Exception:
            pass
        base = os.path.basename(filename)
        self.log(f"✔ Download finished: {base} — post-processing…")
        self._set_stage("Merging / converting… (FFmpeg, can take minutes)",
                        indeterminate=True)
        self._set_step(2)
        self.percent_label.configure(text="100%")
        if self.active_item is not None:
            self.active_item["percent"] = "100%"
            self._update_queue_row(self.active_item)
        self.status_label.configure(
            text="Download finished — merging/converting (FFmpeg)…")

    def _on_postproc_started(self, pp: str, title: str):
        self._last_progress_time = time.time()
        self.log(f"⚙ {pp}: {title or ''}".strip())
        self._set_stage(f"{pp}…", indeterminate=True)
        self.status_label.configure(text=f"{pp}… {title[:60]}")

    def _on_postproc_finished(self):
        self._last_progress_time = time.time()
        self.log("✔ Post-processing done.")

    def _finish_active(self, status: str):
        item = self.active_item
        if item is not None:
            item["status"] = status
            self._update_queue_row(item)
        self._after_item()

    def _succeed(self):
        self._set_step(3)
        self.progress_bar.set(1.0)
        self.percent_label.configure(text="100%")
        self._set_stage_text("Done ✅")
        item = self.active_item
        title = (item or {}).get("title") or "Download"
        if item is not None:
            item["percent"] = "100%"
        self.status_label.configure(text="✅ Done — saved to your folder.")
        self.log("✅ Done — saved successfully.")
        self._notify("viidaaz — download complete", title)
        more = self._pending_count() > 0
        self._finish_active("done")
        if more:
            return  # queue keeps flowing; no popup per item
        self._set_stage_text("Done ✅")
        if messagebox.askyesno("Download complete",
                               "Your file was saved successfully!\n\n"
                               "Open the destination folder now?"):
            self.open_download_folder()

    def _paused(self):
        item = self.active_item
        if item is not None:
            item["status"] = "paused"
            self._update_queue_row(item)
        self._stop_timer()
        self._set_stage_text("Paused ⏸")
        self.status_label.configure(
            text="⏸ Paused — partial file kept. Resume continues where it stopped.")
        self.log("⏸ Paused — resume to continue.")
        try:
            self.pause_btn.configure(state="normal", text="▶ Resume")
        except Exception:
            pass

    def _cancelled(self):
        item = self.active_item
        title = (item or {}).get("title") or "Download"
        self._set_stage_text("Cancelled")
        self.status_label.configure(text="⏹ Cancelled by user.")
        self.log("⏹ Cancelled.")
        self._notify("viidaaz — cancelled", title)
        self._finish_active("cancelled")

    def _fail(self, message: str):
        item = self.active_item
        title = (item or {}).get("title") or "Download"
        if item is not None:
            item["status"] = "failed"
            item["error"] = message
            self._update_queue_row(item)
        self._set_stage_text("Failed ❌")
        self.status_label.configure(text="❌ Download failed — see message.")
        self.log(f"❌ FAILED: {message[:300]}")
        self._last_error = message
        self._notify("viidaaz — download failed", title)
        more = self._pending_count() > 0
        self._finish_active("failed")
        if not more:
            self._show_error_dialog(self._friendly_error(message), message)

    # ------------------------------------------------------------------
    # Copyable error dialog, notifications, thumbnails, drag & drop
    # ------------------------------------------------------------------
    def _show_error_dialog(self, friendly: str, raw: str):
        """Friendly message up front, full technical details one click away."""
        try:
            pal = self._pal()
            dlg = ctk.CTkToplevel(self)
            dlg.title("Download failed")
            dlg.geometry("560x420")
            dlg.minsize(480, 360)
            dlg.configure(fg_color=pal["bg"])
            try:
                dlg.transient(self)
                dlg.grab_set()
            except Exception:
                pass
            dlg.grid_columnconfigure(0, weight=1)
            dlg.grid_rowconfigure(1, weight=1)
            ctk.CTkLabel(dlg, text="❌ Download failed", anchor="w",
                         font=ctk.CTkFont(size=16, weight="bold"),
                         text_color=pal["main"]).grid(
                row=0, column=0, sticky="w", padx=18, pady=(16, 4))
            ctk.CTkLabel(dlg, text=friendly, anchor="w", justify="left",
                         font=ctk.CTkFont(size=12), text_color=pal["muted"],
                         wraplength=520).grid(
                row=0, column=0, sticky="w", padx=18, pady=(36, 8))
            box = ctk.CTkTextbox(dlg, corner_radius=10, fg_color=pal["field"],
                                 border_color=pal["border"], border_width=1,
                                 text_color=pal["logtext"],
                                 font=ctk.CTkFont(family="Consolas", size=11),
                                 wrap="word")
            box.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
            box.insert("end", raw[:4000])
            box.configure(state="disabled")
            row = ctk.CTkFrame(dlg, fg_color="transparent")
            row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(row, text="Copy details", height=36, corner_radius=9,
                          fg_color=pal["accent"],
                          hover_color=pal["accent_hover"],
                          text_color="#FFFFFF",
                          command=lambda: self._copy_text(raw[:4000])).grid(
                row=0, column=1, padx=(0, 8))
            ctk.CTkButton(row, text="Close", height=36, width=100,
                          corner_radius=9, fg_color=pal["ghost"],
                          hover_color=pal["ghost_hover"],
                          text_color=pal["main"],
                          command=dlg.destroy).grid(row=0, column=2)
        except Exception:
            try:
                messagebox.showerror("Download failed", friendly)
            except Exception:
                pass

    def _copy_text(self, text: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.log("📋 Error details copied to clipboard.")
        except Exception:
            pass

    def _notify(self, title: str, message: str):
        """Background completion notice: system toast, else taskbar flash."""
        try:
            from plyer import notification
            icon = _resource_path(os.path.join("assets", "viidaaz.ico"))
            notification.notify(title=title, message=message[:200],
                                app_name="viidaaz",
                                app_icon=icon if os.path.isfile(icon) else None,
                                timeout=8)
            return
        except Exception:
            pass
        self._flash_taskbar()

    def _flash_taskbar(self):
        try:
            import ctypes
            hwnd = self.winfo_id() or 0

            class _Flash(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint),
                            ("hwnd", ctypes.c_void_p),
                            ("dwFlags", ctypes.c_uint),
                            ("uCount", ctypes.c_uint),
                            ("dwTimeout", ctypes.c_uint)]

            info = _Flash(ctypes.sizeof(_Flash), hwnd, 3, 5, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass
        try:
            self.bell()
        except Exception:
            pass

    # -- thumbnails + size estimate (filled by pre-flight) -----------------
    @staticmethod
    def _estimate_size(info: dict, quality: str | None,
                       is_audio: bool) -> int | None:
        """Best-effort byte estimate from advertised format sizes."""
        fmts = info.get("formats") or []

        def _sz(f):
            return f.get("filesize") or f.get("filesize_approx")

        try:
            if is_audio:
                cands = [f for f in fmts
                         if f.get("acodec") != "none" and _sz(f)]
                return max((_sz(f) for f in cands), default=None)
            cap = {"1080p": 1080, "720p": 720, "480p": 480,
                   "360p": 360}.get(quality or "")
            video = [f for f in fmts
                     if f.get("vcodec") != "none" and _sz(f)
                     and (cap is None or (f.get("height") or 0) <= cap)]
            audio = [f for f in fmts
                     if f.get("acodec") != "none" and _sz(f)]
            if not video:
                video = [f for f in fmts
                         if f.get("vcodec") != "none" and _sz(f)]
            if not (video and audio):
                pool = [_sz(f) for f in fmts if _sz(f)]
                return max(pool, default=None)
            return max(_sz(f) for f in video) + max(_sz(f) for f in audio)
        except Exception:
            return None

    def _fetch_thumbnail(self, info: dict):
        vid = info.get("id")
        if not vid or vid in self._thumb_cache:
            return
        thumb_url = info.get("thumbnail")
        if not thumb_url:
            return
        try:
            import urllib.request
            from PIL import Image as _PILImage
            req = urllib.request.Request(
                thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                import io
                img = _PILImage.open(io.BytesIO(resp.read())).convert("RGB")
            img = img.resize((224, 126))
            self._thumb_cache[vid] = img
            self.after(0, lambda: self._paint_thumbnail(vid))
        except Exception:
            pass

    def _paint_thumbnail(self, vid: str):
        try:
            img = self._thumb_cache.get(vid)
            if img is None:
                return
            ci = ctk.CTkImage(light_image=img, dark_image=img, size=(112, 63))
            self._thumb_img = ci  # keep a reference
            self.thumb_label.configure(image=ci, text="")
        except Exception:
            pass

    def _show_video_meta(self, info: dict, size: int | None):
        try:
            self.vmeta.grid()
            title = (info.get("title") or "Unknown title").strip()
            dur = info.get("duration_string") or ""
            parts = [title[:80]]
            sub = "  •  ".join(p for p in
                               [dur, (f"≈ {format_bytes(size)}" if size else "")]
                               if p)
            if sub:
                parts.append(sub)
            self.video_info_label.configure(text="\n".join(parts))
            vid = info.get("id")
            if vid and vid in self._thumb_cache:
                self._paint_thumbnail(vid)
        except Exception:
            pass

    def _clear_video_meta(self):
        try:
            self.vmeta.grid_remove()
            self.thumb_label.configure(image=None, text="")
            self._thumb_img = None
            self.video_info_label.configure(text="No video loaded yet.")
        except Exception:
            pass

    # -- drag & drop (.url / .txt files, or any file holding a link) ------
    def _hook_dropfiles(self):
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            import windnd
            hwnd = self.winfo_id()
            try:
                parent = ctypes.windll.user32.GetParent(hwnd)
                if parent:
                    hwnd = parent
            except Exception:
                pass
            windnd.hook_dropfiles(hwnd, self._on_files_dropped)
            self.log("ℹ Tip: drag a .url or text file onto the window.")
        except Exception:
            pass

    def _on_files_dropped(self, files):
        try:
            for raw in files:
                path = raw.decode("utf-8", "ignore") if isinstance(
                    raw, (bytes, bytearray)) else str(raw)
                url = None
                if path.lower().endswith(".url"):
                    try:
                        with open(path, "r", encoding="utf-8",
                                  errors="ignore") as fh:
                            for line in fh:
                                if line.strip().lower().startswith("url="):
                                    url = line.strip()[4:]
                                    break
                    except Exception:
                        pass
                else:
                    try:
                        with open(path, "r", encoding="utf-8",
                                  errors="ignore") as fh:
                            text = fh.read(2000)
                        m = re.search(r"https?://\S+", text)
                        if m:
                            url = m.group(0)
                    except Exception:
                        pass
                if url:
                    self.after(0, lambda u=url: self._drop_url(u))
                    return
            self._log_from_thread("⚠ No link found in dropped file(s).")
        except Exception:
            pass

    def _drop_url(self, url: str):
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, url)
        self._schedule_title_lookup()
        self.log(f"📥 Dropped link: {url[:80]}")

    # ------------------------------------------------------------------
    # Auto-update — polls GitHub releases, installs the Setup asset
    # ------------------------------------------------------------------
    @staticmethod
    def _ver_tuple(v: str) -> tuple:
        try:
            return tuple(int(p) for p in
                         re.split(r"[.\-+]", v.strip().lstrip("v")) if p.isdigit())
        except Exception:
            return (0,)

    def check_updates_now(self):
        self.log("🔄 Checking for updates…")
        threading.Thread(target=self._check_updates,
                         args=(False,), daemon=True).start()

    def _check_updates(self, silent: bool):
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_OWNER}/"
                f"{GITHUB_REPO}/releases/latest",
                headers={"User-Agent": "viidaaz",
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                rel = json.load(resp)
            tag = str(rel.get("tag_name") or "").strip()
            if not tag or self._ver_tuple(tag) <= self._ver_tuple(APP_VERSION):
                if not silent:
                    self.after(0, lambda: messagebox.showinfo(
                        "Up to date", f"viidaaz {APP_VERSION} is the latest."))
                return
            asset_url = None
            for asset in rel.get("assets") or []:
                if asset.get("name") == UPDATE_ASSET:
                    asset_url = asset.get("browser_download_url")
                    break
            notes = str(rel.get("body") or "")[:800]
            self.after(0, lambda: self._offer_update(tag, notes, asset_url))
        except Exception as exc:  # noqa: BLE001 — offline etc: stay silent(ish)
            if not silent:
                self.after(0, lambda: messagebox.showwarning(
                    "Update check failed",
                    f"Couldn't reach GitHub:\n{exc}"[:300]))

    def _offer_update(self, tag: str, notes: str, asset_url: str | None):
        if not asset_url:
            messagebox.showinfo(
                "Update available",
                f"viidaaz {tag} is out, but no installer was attached.\n"
                f"Get it at github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases")
            return
        text = f"viidaaz {tag} is available (you have {APP_VERSION}).\n"
        if notes:
            text += f"\nWhat's new:\n{notes}\n"
        text += "\nDownload and install it now? The app will exit."
        if not messagebox.askyesno("Update available", text):
            return
        self.log(f"⬇ Downloading update {tag}…")
        threading.Thread(target=self._download_and_install_update,
                         args=(tag, asset_url), daemon=True).start()

    def _download_and_install_update(self, tag: str, asset_url: str):
        try:
            import urllib.request
            tmp = os.path.join(
                os.environ.get("TEMP") or str(Path.home()),
                f"viidaaz-Setup-{tag}.exe")
            req = urllib.request.Request(asset_url,
                                         headers={"User-Agent": "viidaaz"})
            with urllib.request.urlopen(req, timeout=60) as resp, \
                    open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh, length=1024 * 256)
            self._log_from_thread(f"✔ Update saved — launching installer…")
            self.after(0, lambda: self._run_installer(tmp))
        except Exception as exc:  # noqa: BLE001
            self._log_from_thread(f"❌ Update download failed: {exc}")
            self.after(0, lambda: messagebox.showerror(
                "Update failed", f"Couldn't download the update:\n{exc}"[:400]))

    def _run_installer(self, setup_path: str):
        try:
            subprocess.Popen([setup_path], close_fds=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Update failed",
                                 f"Couldn't launch installer:\n{exc}"[:300])
            return
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    @staticmethod
    def _friendly_error(raw: str) -> str:
        low = raw.lower()
        if "private" in low:
            return "This video is private and can't be downloaded."
        if "not a bot" in low or "sign in to confirm" in low:
            return ("YouTube is blocking automated downloads from this network "
                    "(“Sign in to confirm you're not a bot”).\n\n"
                    "Fixes that usually work:\n"
                    "• In ③ Cookies, set YouTube cookies to your browser "
                    "(close the browser first) and retry.\n"
                    "• Or try a different network (e.g. phone hotspot) — "
                    "shared/VPN IPs get flagged most.\n"
                    "• Install Deno (winget install DenoLand.Deno) so all "
                    "formats can be resolved.")
        if "429" in low or "too many requests" in low:
            return ("YouTube rate-limited this IP (HTTP 429 — too many requests).\n\n"
                    "Wait a few minutes and retry, or switch networks. "
                    "Adding YouTube cookies (③ Cookies) also helps.")
        if "unavailable" in low or "removed" in low or "deleted" in low:
            return "This video is unavailable (removed, deleted, or region-blocked)."
        if "sign in" in low or "login" in low or "age" in low:
            return ("This video needs a logged-in / age-verified account.\n"
                    "Set YouTube cookies to your browser in ③ Cookies "
                    "(close the browser first), then retry.")
        if "drm" in low:
            return ("This video is DRM-protected (e.g. YouTube Movies / paid "
                    "content) and cannot be downloaded by any downloader.")
        if ("urlopen" in low or "name resolution" in low or "network" in low
                or "failed to establish" in low or "timed out" in low):
            return ("No internet connection or YouTube is unreachable.\n"
                    "Check your network and try again.")
        if "unsupported url" in low or "no video formats" in low:
            return "That link isn't supported. Please paste a valid YouTube video URL."
        if "javascript runtime" in low or "js runtime" in low or "ejs" in low:
            return ("Some formats need a JavaScript runtime.\n"
                    "Install Deno (winget install DenoLand.Deno) and retry.")
        if "ffmpeg" in low:
            return ("FFmpeg failed during conversion.\nThis build ships its own "
                    "FFmpeg, so this is a conversion error rather than a "
                    f"missing binary.\n\nDetails: {raw[:400]}")
        return f"Something went wrong:\n\n{raw[:600]}"


def main():
    app = ViidaazApp()
    app.mainloop()


if __name__ == "__main__":
    main()
