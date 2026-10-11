#!/usr/bin/env python3
"""
Watermark Clock — NTP-synced UTC+8 time pinned to bottom-right corner.
Per-pixel alpha compositing for smooth anti-aliased text on any background.
"""

import ctypes
from ctypes import wintypes
import threading
import time
import socket
import struct
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# DPI awareness — must run BEFORE `import tkinter`: Tk sets the process to
# SYSTEM_AWARE on import, after which SetProcessDpiAwareness(2) fails and we
# stay stuck on the boot-time system DPI (the "switch monitor, restart fixes
# it" symptom). SetProcessDpiAwarenessContext can still elevate afterwards.
# ---------------------------------------------------------------------------
def _ensure_dpi_awareness():
    try:
        SetCtx = ctypes.windll.user32.SetProcessDpiAwarenessContext
        SetCtx.restype = wintypes.BOOL
        SetCtx.argtypes = [wintypes.HANDLE]
        if SetCtx(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return True
    except Exception:
        pass
    # NOTE: shcore returns HRESULT (no exception on failure), so check it.
    try:
        _spa = ctypes.windll.shcore.SetProcessDpiAwareness
        _spa.restype = ctypes.c_long
        _spa.argtypes = [ctypes.c_int]
        if _spa(2) in (0, 1):  # S_OK / S_FALSE(already set)
            return True
        if _spa(1) in (0, 1):
            return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        pass
    return False


_ensure_dpi_awareness()

import tkinter as tk

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Windows API
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
gdi32  = ctypes.windll.gdi32

WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
GWL_EXSTYLE       = -20

HWND_TOPMOST    = -1
HWND_NOTOPMOST  = -2
SWP_NOMOVE      = 0x0002
SWP_NOSIZE      = 0x0001
SWP_NOACTIVATE  = 0x0010

ULW_ALPHA    = 0x00000002
AC_SRC_ALPHA = 0x01

MONITOR_DEFAULTTONEAREST = 2


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp",             ctypes.c_byte),
        ("BlendFlags",          ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat",         ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          wintypes.DWORD),
        ("biWidth",         wintypes.LONG),
        ("biHeight",        wintypes.LONG),   # negative = top-down DIB
        ("biPlanes",        wintypes.WORD),
        ("biBitCount",      wintypes.WORD),
        ("biCompression",   wintypes.DWORD),
        ("biSizeImage",     wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed",       wintypes.DWORD),
        ("biClrImportant",  wintypes.DWORD),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


# --- ctypes prototypes: declare at import (64-bit safe: without
# restype/argtypes, ctypes assumes 32-bit int and truncates HWND/HANDLE).
# Each declaration is guarded so a missing export on old Windows skips
# only itself, never the rest. ---
def _setup_prototypes():
    H = ctypes.c_void_p

    def _decl(dll, name, rest, args):
        try:
            fn = getattr(dll, name)
            fn.restype = rest
            fn.argtypes = args
        except Exception:
            pass

    I32 = ctypes.c_int
    B = wintypes.BOOL
    _decl(user32, "FindWindowW", H, [wintypes.LPCWSTR, wintypes.LPCWSTR])
    _decl(user32, "GetWindowRect", B, [H, ctypes.POINTER(wintypes.RECT)])
    _decl(user32, "GetWindowLongW", H, [H, I32])
    _decl(user32, "SetWindowLongW", H, [H, I32, wintypes.LONG])
    _decl(user32, "MonitorFromWindow", H, [H, wintypes.DWORD])
    _decl(user32, "MonitorFromPoint", H, [POINT, wintypes.DWORD])
    _decl(user32, "GetMonitorInfoW", B, [H, ctypes.POINTER(MONITORINFO)])
    _decl(user32, "GetDpiForWindow", wintypes.UINT, [H])
    _decl(user32, "GetDC", H, [H])
    _decl(user32, "ReleaseDC", I32, [H, H])
    _decl(user32, "UpdateLayeredWindow", B, [
        H, H,
        ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
        H, ctypes.POINTER(POINT),
        wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD])
    _decl(user32, "GetSystemMetrics", I32, [I32])
    _decl(user32, "SetWindowPos", B,
          [H, H, I32, I32, I32, I32, wintypes.UINT])
    _decl(gdi32, "GetDeviceCaps", I32, [H, I32])
    _decl(gdi32, "CreateCompatibleDC", H, [H])
    _decl(gdi32, "CreateDIBSection", H, [
        H, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
        ctypes.POINTER(H), H, wintypes.DWORD])
    _decl(gdi32, "SelectObject", H, [H, H])
    _decl(gdi32, "DeleteObject", B, [H])
    _decl(gdi32, "DeleteDC", B, [H])
    _decl(ctypes.windll.shcore, "GetDpiForMonitor", ctypes.c_long, [
        H, I32,
        ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)])


LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "clock_debug.log")


def _log(msg):
    try:
        if (os.path.exists(LOG_PATH)
                and os.path.getsize(LOG_PATH) > 200 * 1024):
            os.remove(LOG_PATH)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%H:%M:%S") + " " + msg + "\n")
    except Exception:
        pass


def _get_process_awareness():
    """0=unaware 1=system 2=per-monitor. None if the query failed."""
    try:
        v = ctypes.c_int(-1)
        _gpa = ctypes.windll.shcore.GetProcessDpiAwareness
        _gpa.restype = ctypes.c_long
        _gpa.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_int)]
        if _gpa(None, ctypes.byref(v)) == 0:
            return int(v.value)
    except Exception:
        pass
    return None


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD)]


_setup_prototypes()


def _get_window_rect(hwnd):
    try:
        r = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None


def _get_dpi_for_window(hwnd):
    """Current monitor's DPI for the given window. Falls back to 96."""
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        if dpi:
            return int(dpi)
    except Exception:
        pass
    try:
        mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if mon:
            dx, dy = wintypes.UINT(), wintypes.UINT()
            if ctypes.windll.shcore.GetDpiForMonitor(
                    mon, 0, ctypes.byref(dx),
                    ctypes.byref(dy)) == 0 and dx.value:
                return int(dx.value)
    except Exception:
        pass
    try:
        hdc = user32.GetDC(0)
        dpi = gdi32.GetDeviceCaps(hdc, 90)  # LOGPIXELSY
        user32.ReleaseDC(0, hdc)
        if dpi:
            return int(dpi)
    except Exception:
        pass
    return 96


def get_monitor_work_area(hwnd):
    """Work area (excluding taskbar) of the monitor holding hwnd."""
    try:
        mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not mon:
            return None
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return (mi.rcWork.left, mi.rcWork.top,
                    mi.rcWork.right, mi.rcWork.bottom)
    except Exception:
        pass
    return None


def _get_dpi_for_point(x, y):
    """DPI of the monitor containing virtual point (x, y). None if unknown."""
    try:
        mon = user32.MonitorFromPoint(POINT(int(x), int(y)),
                                      MONITOR_DEFAULTTONEAREST)
        if mon:
            dx, dy = wintypes.UINT(), wintypes.UINT()
            if ctypes.windll.shcore.GetDpiForMonitor(
                    mon, 0, ctypes.byref(dx),
                    ctypes.byref(dy)) == 0 and dx.value:
                return int(dx.value)
    except Exception:
        pass
    return None


def get_monitor_work_area_for_point(x, y):
    """Work area of the monitor containing virtual point (x, y)."""
    try:
        mon = user32.MonitorFromPoint(POINT(int(x), int(y)),
                                      MONITOR_DEFAULTTONEAREST)
        if not mon:
            return None
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return (mi.rcWork.left, mi.rcWork.top,
                    mi.rcWork.right, mi.rcWork.bottom)
    except Exception:
        pass
    return None


def get_screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def get_taskbar_rect():
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not hwnd:
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


# ---------------------------------------------------------------------------
# NTP
# ---------------------------------------------------------------------------
NTP_PORT   = 123
NTP_DELTA  = 2208988800
NTP_SERVERS = ["ntp.aliyun.com", "pool.ntp.org", "time.windows.com"]


def _ntp_unix(data, offset):
    a, b = struct.unpack("!II", data[offset:offset + 8])
    return a - NTP_DELTA + b / 2 ** 32


def ntp_sync(timeout=3.0):
    for srv in NTP_SERVERS:
        try:
            pkt = b"\x23" + b"\x00" * 47
            t1 = time.time()
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            s.sendto(pkt, (srv, NTP_PORT))
            data, _ = s.recvfrom(1024)
            t4 = time.time()
            s.close()
            if len(data) >= 48:
                t2 = _ntp_unix(data, 32)
                t3 = _ntp_unix(data, 40)
                return True, ((t2 - t1) + (t3 - t4)) / 2.0
        except Exception:
            pass
    return False, 0.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clock_config.json")
DEFAULT = {
    "font_size": 12,
    "color": "#cccccc",
    "transparent": True,
    "auto_scale": True,
    "always_on_top": True,
}
WDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TZ8 = timezone(timedelta(hours=8))


def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return {**DEFAULT, **json.load(f)}
    except Exception:
        return dict(DEFAULT)


def save_cfg(cfg):
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        _log(f"save cfg error: {e!r}")


# ---------------------------------------------------------------------------
# TrueType font loader
# ---------------------------------------------------------------------------
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Consolas TrueType font at the requested size.
       Falls back through several paths, then to PIL default."""
    font_name = "consola.ttf"
    paths = [
        font_name,                                                  # cwd
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", font_name),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "consolab.ttf"),
        "cour.ttf",
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "cour.ttf"),
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    # Ultimate fallback — PIL's built-in bitmap font (poor quality)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Watermark Clock
# ---------------------------------------------------------------------------
class WatermarkClock:
    def __init__(self):
        self.cfg = load_cfg()
        self.ntp_offset = 0.0

        self._font_size = self.cfg["font_size"]
        self._fg_color = self.cfg["color"]
        self._auto_scale = bool(self.cfg.get("auto_scale", True))
        self._always_on_top = bool(self.cfg.get("always_on_top", True))

        # Parse foreground color
        fg_str = self._fg_color.lstrip("#")
        self._fg_rgb = (int(fg_str[0:2], 16),
                        int(fg_str[2:4], 16),
                        int(fg_str[4:6], 16))

        # ---- tkinter window (shell only — we paint via UpdateLayeredWindow) ----
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.configure(bg="#000000")

        self.root.geometry("120x50")
        self.root.update_idletasks()

        hwnd = int(self.root.frame(), 16)
        self._hwnd = hwnd
        self.tray = None

        # Enable WS_EX_LAYERED so UpdateLayeredWindow can take over painting
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        self._apply_topmost()

        # DPI of the monitor we belong to (anchor-based, not boot snapshot)
        if self._auto_scale:
            try:
                self._dpi = (_get_dpi_for_point(*self._anchor_point())
                             or _get_dpi_for_window(hwnd))
            except Exception:
                self._dpi = _get_dpi_for_window(hwnd)
        else:
            self._dpi = 96
        self._apply_layout()
        _log(f"init: awareness={_get_process_awareness()} dpi={self._dpi} "
             f"anchor={self._anchor_point()} win={self._win_w}x{self._win_h}")

        # Pre-compute blended background color for non-transparent mode
        # Dark bg at 75 % opacity → RGBA (24, 24, 24, 191)
        self._bg_rgba = (24, 24, 24, 191) if not self.cfg["transparent"] else (0, 0, 0, 0)

        self._last_lines = (None, None)

        self.root.geometry(f"{self._win_w}x{self._win_h}")
        self._dock()
        self.root.deiconify()

        # Initial paint
        self._paint(force=True)

        # Periodic tasks
        self._tick()
        self.root.after(2000, self._check_pos)
        self._start_ntp_loop()
        self._tray()
        # Never die silently on a Tk callback exception (e.g. transient
        # failures during a display-topology change): log and keep going.
        self.root.report_callback_exception = self._on_tk_error

    def _on_tk_error(self, exc, val, tb):
        try:
            import traceback
            _log("tk error: " + "".join(
                traceback.format_exception(exc, val, tb)).strip())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Always on top
    # ------------------------------------------------------------------
    def _apply_topmost(self):
        """Apply HWND_TOPMOST / NOTOPMOST so other windows can't cover us
        (or can, when the user opts out). Tk's -topmost alone is flaky
        once UpdateLayeredWindow owns the paint path, so set the Win32
        z-order directly and keep the Tk flag in sync."""
        try:
            insert = HWND_TOPMOST if self._always_on_top else HWND_NOTOPMOST
            user32.SetWindowPos(self._hwnd, insert, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception as e:
            _log(f"topmost error: {e!r}")
        try:
            self.root.attributes("-topmost", self._always_on_top)
        except Exception:
            pass

    def _toggle_topmost(self, icon=None, item=None):
        self._always_on_top = not self._always_on_top
        self.cfg["always_on_top"] = self._always_on_top
        save_cfg(self.cfg)
        self._apply_topmost()
        _log(f"always_on_top={self._always_on_top}")
        try:
            if icon is not None:
                icon.update_menu()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # DPI / layout
    # ------------------------------------------------------------------
    def _pil_font_size(self, dpi):
        # Scale from "tkinter-equivalent points" (at window DPI) to PIL
        # points (72 dpi). tkinter interprets positive font sizes as points
        # at system DPI; PIL always assumes 72 dpi.
        return max(1, int(round(self._font_size * dpi / 72)))

    def _apply_layout(self):
        """(Re)build font + metrics + window size for the current DPI."""
        self._font = _load_font(self._pil_font_size(self._dpi))
        # Padding / gap scale with DPI so proportions stay identical
        scale = self._dpi / 96.0
        self._pad_x = max(2, int(round(4 * scale)))
        self._pad_y = max(1, int(round(2 * scale)))
        self._line_gap = max(2, int(round(5 * scale)))
        self._measure_text()
        # Window size = text + padding
        self._win_w = self._text_w + self._pad_x * 2
        self._win_h = self._text_h + self._pad_y * 2

    def _on_dpi_changed(self, new_dpi):
        if not self._auto_scale:
            return False
        if new_dpi and new_dpi != self._dpi:
            _log(f"dpi {self._dpi}->{new_dpi}")
            self._dpi = int(new_dpi)
            self._apply_layout()
            self.root.geometry(f"{self._win_w}x{self._win_h}")
            self._dock()
            self._paint(force=True)
            return True
        return False

    # ------------------------------------------------------------------
    # Text measurement
    # ------------------------------------------------------------------
    def _measure_text(self):
        """Measure line widths and height for right-aligned two-line layout."""
        line1 = "00:00:00"
        line2 = "2026-01-01 Mon"
        ascent, descent = self._font.getmetrics()
        self._line_h = ascent + descent      # full typographic line height

        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bbox1 = draw.textbbox((0, 0), line1, font=self._font)
        bbox2 = draw.textbbox((0, 0), line2, font=self._font)
        self._text_w = max(bbox1[2] - bbox1[0], bbox2[2] - bbox2[0])
        self._text_h = self._line_h * 2 + self._line_gap

    # ------------------------------------------------------------------
    # Positioning — stick to ONE monitor via a virtual-screen anchor point
    # ------------------------------------------------------------------
    def _anchor_point(self):
        """Bottom-right corner we belong to (10px/8px inside the work area)."""
        if hasattr(self, "_ax"):
            return self._ax, self._ay
        tb = get_taskbar_rect()
        if tb:
            return tb[0] + tb[2] - 10, tb[1] - 8
        sw, sh = get_screen_size()
        return sw - 10, sh - 52

    def _dock(self):
        """Pin to the anchor's monitor; refresh the anchor from the work
        area so a taskbar move updates it. If the anchor's monitor vanished
        (unplugged), fall back to the taskbar's current monitor."""
        try:
            work = get_monitor_work_area_for_point(*self._anchor_point())
        except AttributeError:
            work = None
        if work is None:
            tb = get_taskbar_rect()
            if tb:
                self._ax, self._ay = tb[0] + tb[2] - 10, tb[1] - 8
                work = get_monitor_work_area_for_point(self._ax, self._ay)
        if work is None:
            sw, sh = get_screen_size()
            self._x = sw - self._win_w - 10
            self._y = sh - 52 - self._win_h
            return
        self._ax, self._ay = work[2] - 10, work[3] - 8
        self._x = work[2] - self._win_w - 10
        self._y = work[3] - self._win_h - 8

    def _reanchor(self):
        """Re-read DPI at the anchor (not at the window) and re-dock.

        The window itself never moves between monitors — Windows keeps it
        where it is. But its *position* may have landed on a different
        monitor after a topology change, so asking the window for its DPI
        reads the WRONG monitor. The anchor is the source of truth."""
        changed = False
        if self._auto_scale:
            try:
                dpi = _get_dpi_for_point(*self._anchor_point())
                if dpi:
                    changed = self._on_dpi_changed(dpi)
            except Exception:
                pass
        if not changed:
            try:
                self._dock()
            except Exception:
                pass
            try:
                self._paint(force=True)
            except Exception:
                pass

    def _check_pos(self):
        """Fallback poll: re-dock + pick up DPI changes on a timer.

        Pure polling (no window subclassing): hooking Tk's WndProc from
        Python is fragile across display-topology changes and can take
        the whole process down, so DPI drift is caught here instead."""
        try:
            dpi = _get_dpi_for_point(*self._anchor_point())
            if dpi and dpi != self._dpi:
                _log(f"poll: dpi {self._dpi}->{dpi}")
            self._reanchor()
            if self._always_on_top:
                self._apply_topmost()
        except Exception as e:
            _log(f"poll error: {e!r}")
        self.root.after(2000, self._check_pos)

    # ------------------------------------------------------------------
    # Per-pixel-alpha paint via UpdateLayeredWindow
    # ------------------------------------------------------------------
    def _paint(self, force=False):
        """Render the clock text onto a 32-bit RGBA bitmap and hand it to
           UpdateLayeredWindow for per-pixel alpha compositing.

           This replaces the old color-key approach — every pixel carries
           its own alpha value, so anti-aliased edges blend smoothly into
           whatever wallpaper or window sits behind the clock."""
        # --- Build the text ---
        utc = datetime.now(timezone.utc) + timedelta(seconds=self.ntp_offset)
        dt = utc.astimezone(TZ8)
        line1 = dt.strftime("%H:%M:%S")
        line2 = dt.strftime("%Y-%m-%d ") + WDAYS[dt.weekday()]

        # Skip the expensive GDI round-trip when nothing changed
        if not force and (line1, line2) == self._last_lines:
            return
        self._last_lines = (line1, line2)

        # --- Render to PIL RGBA image ---
        img = Image.new("RGBA", (self._win_w, self._win_h), self._bg_rgba)
        draw = ImageDraw.Draw(img)

        # Measure each line for right-alignment
        bbox1 = draw.textbbox((0, 0), line1, font=self._font)
        bbox2 = draw.textbbox((0, 0), line2, font=self._font)
        w1 = bbox1[2] - bbox1[0]
        w2 = bbox2[2] - bbox2[0]
        max_w = max(w1, w2)

        # Right-align — both lines end at the same x coordinate
        draw.text((self._pad_x + max_w - w1, self._pad_y), line1,
                  font=self._font, fill=self._fg_rgb + (255,))
        draw.text((self._pad_x + max_w - w2, self._pad_y + self._line_h + self._line_gap), line2,
                  font=self._font, fill=self._fg_rgb + (255,))

        # Convert straight-alpha RGBA → premultiplied BGRA (what Windows wants)
        pixels = bytearray(img.tobytes("raw", "BGRA"))
        for i in range(0, len(pixels), 4):
            a = pixels[i + 3]
            if a < 255:
                pixels[i]     = (pixels[i]     * a) // 255
                pixels[i + 1] = (pixels[i + 1] * a) // 255
                pixels[i + 2] = (pixels[i + 2] * a) // 255

        # --- Create a 32-bit DIB section + blit (skip frame on any
        # transient GDI failure instead of crashing) ---
        hdc_screen = None
        mem_dc = None
        h_bmp = None
        old_bmp = None
        try:
            hdc_screen = user32.GetDC(0)
            if not hdc_screen:
                return
            mem_dc = gdi32.CreateCompatibleDC(hdc_screen)
            if not mem_dc:
                return

            bmi = BITMAPINFOHEADER()
            bmi.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth       = self._win_w
            bmi.biHeight      = -self._win_h   # negative → top-down
            bmi.biPlanes      = 1
            bmi.biBitCount    = 32
            bmi.biCompression = 0              # BI_RGB

            pv_bits = ctypes.c_void_p()
            h_bmp = gdi32.CreateDIBSection(
                mem_dc, ctypes.byref(bmi), 0, ctypes.byref(pv_bits), None, 0)
            if not h_bmp or not pv_bits:
                return
            ctypes.memmove(pv_bits, bytes(pixels), len(pixels))

            old_bmp = gdi32.SelectObject(mem_dc, h_bmp)

            # --- Hand the bitmap to the desktop compositor ---
            blend = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
            sz    = SIZE(self._win_w, self._win_h)
            pt_src = POINT(0, 0)
            pt_dst = POINT(self._x, self._y)

            user32.UpdateLayeredWindow(
                self._hwnd, hdc_screen,
                ctypes.byref(pt_dst), ctypes.byref(sz),
                mem_dc, ctypes.byref(pt_src),
                0, ctypes.byref(blend), ULW_ALPHA)
        except Exception as e:
            _log(f"paint error: {e!r}")
            return
        finally:
            # --- Cleanup GDI objects ---
            try:
                if mem_dc:
                    gdi32.SelectObject(mem_dc,
                                       old_bmp if old_bmp else h_bmp)
                if h_bmp:
                    gdi32.DeleteObject(h_bmp)
                if mem_dc:
                    gdi32.DeleteDC(mem_dc)
                if hdc_screen:
                    user32.ReleaseDC(0, hdc_screen)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------
    def _tick(self):
        self._paint()
        self.root.after(200, self._tick)

    # ------------------------------------------------------------------
    # NTP
    # ------------------------------------------------------------------
    def _start_ntp_loop(self):
        self._sync_in_progress = False
        self._auto_sync()

    def _auto_sync(self):
        self._do_sync(manual=False)
        self.root.after(3600000, self._auto_sync)

    def _manual_sync(self, icon=None, item=None):
        self._do_sync(manual=True)

    def _do_sync(self, manual):
        if getattr(self, "_sync_in_progress", False):
            if manual:
                _log("ntp manual: already in progress, skipped")
            return
        self._sync_in_progress = True

        def worker():
            ok, off = ntp_sync()

            def done():
                self._sync_in_progress = False
                if ok:
                    self.ntp_offset = off
                    self._paint(force=True)
                    _log(f"ntp {'manual' if manual else 'auto'}: ok "
                         f"offset={off:+.3f}s")
                else:
                    _log(f"ntp {'manual' if manual else 'auto'}: "
                         f"fail, keep offset={self.ntp_offset:+.3f}s")

            try:
                self.root.after(0, done)
            except Exception as e:
                self._sync_in_progress = False
                _log(f"ntp done error: {e!r}")

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------
    def _tray(self):
        try:
            import pystray
            img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.text((4, 8), "T", fill="white")
            self.tray = pystray.Icon(
                "wm_clock", img, "UTC+8 Clock",
                pystray.Menu(
                    pystray.MenuItem(
                        "Always on top",
                        self._toggle_topmost,
                        checked=lambda item: self._always_on_top),
                    pystray.MenuItem("Sync now", self._manual_sync),
                    pystray.MenuItem("Exit", self.quit),
                )
            )
            threading.Thread(target=self.tray.run, daemon=True).start()
        except ImportError:
            self.tray = None

    def quit(self, *a):
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()
        os._exit(0)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    WatermarkClock().run()
