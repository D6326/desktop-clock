#!/usr/bin/env python3
"""
Watermark Clock — NTP-synced UTC+8 time pinned to bottom-right corner.
Per-pixel alpha compositing for smooth anti-aliased text on any background.
"""

import tkinter as tk
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

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# DPI awareness — must be called before any window creation
# ---------------------------------------------------------------------------
try:
    # Windows 10 1703+: per-monitor DPI v2
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Windows API
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
gdi32  = ctypes.windll.gdi32

WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
GWL_EXSTYLE       = -20

ULW_ALPHA    = 0x00000002
AC_SRC_ALPHA = 0x01


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
}
WDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TZ8 = timezone(timedelta(hours=8))

# System DPI — used to match PIL's 72-dpi font sizing to the actual display.
# tkinter interprets positive font sizes as points at system DPI; PIL always
# assumes 72 dpi.  Without this correction the text renders ~25 % too small.
_hdc = user32.GetDC(0)
_SYS_DPI = gdi32.GetDeviceCaps(_hdc, 90)  # LOGPIXELSY
user32.ReleaseDC(0, _hdc)


def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return {**DEFAULT, **json.load(f)}
    except Exception:
        return dict(DEFAULT)


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
        # Scale from "tkinter-equivalent points" (at system DPI) to PIL points (72 dpi)
        self._font = _load_font(int(self._font_size * _SYS_DPI / 72))

        # Parse foreground color
        fg_str = self._fg_color.lstrip("#")
        self._fg_rgb = (int(fg_str[0:2], 16),
                        int(fg_str[2:4], 16),
                        int(fg_str[4:6], 16))

        # Padding around text inside the bitmap
        self._pad_x = 4
        self._pad_y = 2

        # Measure text bounding-box from a sample string
        self._measure_text()

        # Window size = text + padding
        self._win_w = self._text_w + self._pad_x * 2
        self._win_h = self._text_h + self._pad_y * 2

        # Pre-compute blended background color for non-transparent mode
        # Dark bg at 75 % opacity → RGBA (24, 24, 24, 191)
        self._bg_rgba = (24, 24, 24, 191) if not self.cfg["transparent"] else (0, 0, 0, 0)

        # ---- tkinter window (shell only — we paint via UpdateLayeredWindow) ----
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#000000")

        self.root.geometry(f"{self._win_w}x{self._win_h}")
        self.root.update_idletasks()

        hwnd = int(self.root.frame(), 16)
        self._hwnd = hwnd

        # Enable WS_EX_LAYERED so UpdateLayeredWindow can take over painting
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)

        self._dock()
        self.root.deiconify()

        # Initial paint
        self._paint()

        # Periodic tasks
        self._tick()
        self.root.after(5000, self._check_pos)
        self._sync_ntp()
        self._tray()

    # ------------------------------------------------------------------
    # Text measurement
    # ------------------------------------------------------------------
    def _measure_text(self):
        """Measure line widths and height for right-aligned two-line layout."""
        line1 = "00:00:00"
        line2 = "2026-01-01 Mon"
        ascent, descent = self._font.getmetrics()
        self._line_h = ascent + descent      # full typographic line height
        self._line_gap = 5                   # extra spacing between the two lines

        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bbox1 = draw.textbbox((0, 0), line1, font=self._font)
        bbox2 = draw.textbbox((0, 0), line2, font=self._font)
        self._text_w = max(bbox1[2] - bbox1[0], bbox2[2] - bbox2[0])
        self._text_h = self._line_h * 2 + self._line_gap

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------
    def _dock(self):
        """Calculate the window position — bottom-right, above taskbar."""
        tb = get_taskbar_rect()
        if tb:
            self._x = tb[0] + tb[2] - self._win_w - 10
            self._y = tb[1] - self._win_h - 8
        else:
            sw, sh = get_screen_size()
            self._x = sw - self._win_w - 10
            self._y = sh - 52 - self._win_h

    def _check_pos(self):
        """Periodically re-dock in case the taskbar moves."""
        self._dock()
        self.root.after(5000, self._check_pos)

    # ------------------------------------------------------------------
    # Per-pixel-alpha paint via UpdateLayeredWindow
    # ------------------------------------------------------------------
    def _paint(self):
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

        # --- Create a 32-bit DIB section ---
        hdc_screen = user32.GetDC(0)
        mem_dc = gdi32.CreateCompatibleDC(hdc_screen)

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

        # --- Cleanup GDI objects ---
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(h_bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, hdc_screen)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------
    def _tick(self):
        self._paint()
        self.root.after(200, self._tick)

    # ------------------------------------------------------------------
    # NTP
    # ------------------------------------------------------------------
    def _sync_ntp(self, *_):
        def worker():
            ok, off = ntp_sync()
            if ok:
                self.ntp_offset = off
            self.root.after(3600000, self._sync_ntp)

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
                    pystray.MenuItem("Sync now", self._sync_ntp),
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
