#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capturas: capturas de pantalla completas o recortadas que se guardan solas
en el Escritorio con la fecha y la hora en el nombre.

Compatible con Windows, macOS y Linux (X11; en Wayland usa grim o
gnome-screenshot). El recorte se hace sobre una captura congelada de la
pantalla: se oscurece todo y la zona elegida se ve nitida.
"""

import argparse
import ctypes
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageEnhance, ImageGrab, ImageTk

APP_NAME = "Capturas"
VERSION = "1.0.0"

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

if IS_WINDOWS:
    from ctypes import wintypes

# --------------------------------------------------------------------------- #
# Tema
# --------------------------------------------------------------------------- #
BG = "#16171a"
CARD = "#22242a"
FG = "#f2f3f5"
MUTED = "#9aa0a6"
ACCENT = "#2f81f7"
ACCENT_HOVER = "#4a94ff"
GHOST = "#2c2f36"
GHOST_HOVER = "#383c45"
BORDER = "#00d1ff"
FONT = "Segoe UI" if IS_WINDOWS else "Helvetica"

# Atajos globales (solo Windows). id: (modificadores, tecla, modo, nombre)
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEYS = {
    1: (MOD_CONTROL | MOD_ALT, "s", "full", "Ctrl+Alt+S"),
    2: (MOD_CONTROL | MOD_ALT, "r", "crop", "Ctrl+Alt+R"),
}
HOTKEY_MODES = {hid: data[2] for hid, data in HOTKEYS.items()}

# Windows: metricas del escritorio virtual
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
HWND_TOPMOST = -1
SWP_SHOWWINDOW = 0x0040
GA_ROOT = 2

if IS_WINDOWS:
    # Prototipos con tipos correctos: sin ellos SetWindowPos falla en 64 bits.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL


# --------------------------------------------------------------------------- #
# Plataforma: rutas, pantalla y captura
# --------------------------------------------------------------------------- #
def enable_dpi_awareness():
    """Coordenadas reales de pantalla en Windows (evita recortes borrosos)."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


FOLDERID_DESKTOP = _GUID(
    0xB4BFCC3A,
    0xDB2C,
    0x424C,
    (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41),
)


def desktop_dir():
    """Ruta real del Escritorio en cualquier sistema."""
    home = Path.home()

    if IS_WINDOWS:
        try:
            ptr = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(FOLDERID_DESKTOP), 0, None, ctypes.byref(ptr)
            )
            if res == 0:
                path = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if path and os.path.isdir(path):
                    return Path(path)
        except Exception:
            pass

    if IS_LINUX:
        # Respeta XDG (Escritorio traducido, p. ej. ~/Escritorio).
        try:
            cfg = home / ".config" / "user-dirs.dirs"
            if cfg.is_file():
                for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR="):
                        raw = line.split("=", 1)[1].strip().strip('"')
                        raw = raw.replace("$HOME", str(home))
                        candidate = Path(os.path.expandvars(raw))
                        if candidate.is_dir():
                            return candidate
        except Exception:
            pass

    for name in ("Desktop", "Escritorio", "Bureau", "Schreibtisch"):
        candidate = home / name
        if candidate.is_dir():
            return candidate

    return home


def resource_path(name):
    """Ruta de un recurso, tambien dentro de un .exe de PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def open_folder(path):
    path = str(path)
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def virtual_bounds():
    """Rectangulo que ocupa el escritorio completo (solo Windows)."""
    u = ctypes.windll.user32
    return (
        u.GetSystemMetrics(SM_XVIRTUALSCREEN),
        u.GetSystemMetrics(SM_YVIRTUALSCREEN),
        u.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        u.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _grab_with_tool(argv, output):
    """Ejecuta una herramienta externa de captura y devuelve la imagen."""
    if shutil.which(argv[0]) is None:
        return None
    try:
        subprocess.run(
            argv, check=True, timeout=20,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if output.exists() and output.stat().st_size:
            return Image.open(output).convert("RGB")
    except Exception:
        return None
    return None


def _grab_linux_fallback():
    folder = Path(tempfile.mkdtemp(prefix="capturas_"))
    out = folder / "shot.png"

    candidates = []
    if os.environ.get("WAYLAND_DISPLAY"):
        candidates += [["grim", str(out)]]
    candidates += [
        ["gnome-screenshot", "-f", str(out)],
        ["spectacle", "-b", "-n", "-o", str(out)],
        ["scrot", "-o", str(out)],
        ["maim", str(out)],
        ["import", "-window", "root", str(out)],
    ]

    for argv in candidates:
        img = _grab_with_tool(argv, out)
        if img is not None:
            return img

    raise RuntimeError(
        "No se pudo capturar la pantalla.\n\n"
        "En X11 instala uno de estos: scrot, maim o gnome-screenshot.\n"
        "En Wayland instala grim (recomendado) o gnome-screenshot."
    )


def grab_desktop():
    """Devuelve (imagen RGB de todo el escritorio, (x, y, ancho, alto))."""
    if IS_WINDOWS:
        vx, vy, vw, vh = virtual_bounds()
        img = ImageGrab.grab(bbox=(vx, vy, vx + vw, vy + vh), all_screens=True)
        return img.convert("RGB"), (vx, vy, vw, vh)

    if IS_MAC:
        try:
            img = ImageGrab.grab()
        except Exception:
            img = None
        if img is None:
            folder = Path(tempfile.mkdtemp(prefix="capturas_"))
            out = folder / "shot.png"
            img = _grab_with_tool(["screencapture", "-x", str(out)], out)
        if img is None:
            raise RuntimeError(
                "No se pudo capturar la pantalla.\n\n"
                "Revisa Ajustes del Sistema > Privacidad y seguridad > "
                "Grabacion de pantalla y permite el acceso a Terminal/Python."
            )
        img = img.convert("RGB")
        return img, (0, 0, img.width, img.height)

    # Linux
    try:
        img = ImageGrab.grab()
        img.load()
    except Exception:
        img = _grab_linux_fallback()
    img = img.convert("RGB")
    return img, (0, 0, img.width, img.height)


def save_capture(img, outdir=None, prefix="Captura"):
    """Guarda el PNG en el Escritorio (o en outdir) con fecha y hora."""
    folder = Path(outdir) if outdir else desktop_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = folder / ("%s_%s.png" % (prefix, stamp))
    n = 2
    while path.exists():
        path = folder / ("%s_%s_%d.png" % (prefix, stamp, n))
        n += 1
    img.save(str(path), "PNG")
    return path


def single_instance_guard():
    """Windows: evita abrir la app dos veces."""
    if not IS_WINDOWS:
        return True
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "CapturasApp_Pantalla_Mutex")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None, "La aplicacion de capturas ya esta abierta.", APP_NAME, 0x40
        )
        return None
    return handle


# --------------------------------------------------------------------------- #
# Atajos globales (Windows): hilo propio con su bucle de mensajes
# --------------------------------------------------------------------------- #
def _hotkey_worker(events):
    """Tk consume los WM_HOTKEY, asi que el registro vive en otro hilo.

    Solo se envian avisos a la ventana a traves de la cola.
    """
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.RegisterHotKey.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
    ]
    u.RegisterHotKey.restype = wintypes.BOOL
    u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    u.GetMessageW.restype = ctypes.c_int

    registered, failed = [], []
    for hid, (mods, key, _mode, name) in HOTKEYS.items():
        try:
            ok = u.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, ord(key.upper()))
        except Exception:
            ok = 0
        if ok:
            registered.append(hid)
        else:
            failed.append(name)

    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
    events.put(("ready", (failed, thread_id)))

    msg = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            events.put(("hotkey", int(msg.wParam)))

    for hid in registered:
        try:
            u.UnregisterHotKey(None, hid)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Capa de recorte
# --------------------------------------------------------------------------- #
class CropOverlay(tk.Toplevel):
    """Captura congelada a tamano real: arrastra para elegir la zona.

    Si la imagen no cabe en la pantalla (macOS Retina, escritorios virtuales
    grandes) se muestra escalada y el recorte se devuelve a resolucion real.
    """

    def __init__(self, parent, image, bounds, on_confirm, on_cancel):
        super().__init__(parent)
        self.image = image
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.start = None
        self.box = None
        self.preview_item = None
        self.preview_photo = None
        self.rect_item = None
        self.hint_items = []
        self.size_bg = None
        self.size_text = None
        self._closed = False

        vx, vy, vw, vh = bounds
        if IS_WINDOWS:
            # 1:1 en todos los monitores
            self.scale = max(0.05, min(1.0, vw / float(image.width)))
        else:
            # Ajuste a la pantalla principal (puntos logicos en macOS).
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.scale = min(1.0, sw / float(image.width), sh / float(image.height))
            vx, vy = 0, 0

        self.disp_w = max(1, int(round(image.width * self.scale)))
        self.disp_h = max(1, int(round(image.height * self.scale)))

        self.overrideredirect(True)
        self.configure(bg="black")
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.geometry("%dx%d+%d+%d" % (self.disp_w, self.disp_h, max(0, vx), max(0, vy)))

        canvas = tk.Canvas(
            self, width=self.disp_w, height=self.disp_h, bg="black",
            highlightthickness=0, bd=0, cursor="crosshair",
        )
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        view = image if self.scale == 1.0 else image.resize(
            (self.disp_w, self.disp_h), Image.LANCZOS
        )
        self.view = view
        dim = ImageEnhance.Brightness(view).enhance(0.32)
        self.base_photo = ImageTk.PhotoImage(dim)
        canvas.create_image(0, 0, anchor="nw", image=self.base_photo)

        self._draw_hint()

        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Button-3>", lambda e: self.cancel())
        self.bind("<Escape>", lambda e: self.cancel())
        self.bind("<Return>", lambda e: self.confirm())
        self.bind("<KP_Enter>", lambda e: self.confirm())

        self.update_idletasks()
        if IS_WINDOWS:
            # Coordenadas negativas: Tk las lee como distancia al borde derecho.
            self._place_on_virtual_screen(vx, vy, self.disp_w, self.disp_h)
        self.lift()
        try:
            self.grab_set()
        except Exception:
            pass
        self.focus_force()
        self.after(30, self._safe_focus)
        if IS_WINDOWS:
            self.after(80, lambda: self._place_on_virtual_screen(
                vx, vy, self.disp_w, self.disp_h))

    def _safe_focus(self):
        if self.winfo_exists():
            self.focus_force()

    def _place_on_virtual_screen(self, vx, vy, w, h):
        try:
            if not self.winfo_exists():
                return
            hwnd = _user32.GetAncestor(self.winfo_id(), GA_ROOT) or self.winfo_id()
            _user32.SetWindowPos(hwnd, HWND_TOPMOST, vx, vy, w, h, SWP_SHOWWINDOW)
        except Exception:
            pass

    # -- dibujo ------------------------------------------------------------- #
    def _draw_hint(self):
        text = "Arrastra para seleccionar   ·   Enter para guardar   ·   Esc para cancelar"
        shadow = self.canvas.create_text(
            self.disp_w // 2 + 1, 29, text=text, fill="#000000",
            font=(FONT, 11, "bold"), anchor="n",
        )
        main = self.canvas.create_text(
            self.disp_w // 2, 28, text=text, fill="#ffffff",
            font=(FONT, 11, "bold"), anchor="n",
        )
        self.hint_items = [shadow, main]

    def _clear_hint(self):
        for item in self.hint_items:
            self.canvas.delete(item)
        self.hint_items = []

    def _draw_selection(self, x1, y1, x2, y2):
        c = self.canvas
        w, h = x2 - x1, y2 - y1
        if w < 2 or h < 2:
            return

        crop = self.view.crop((x1, y1, x2, y2))
        self.preview_photo = ImageTk.PhotoImage(crop)
        if self.preview_item is None:
            self.preview_item = c.create_image(
                x1, y1, anchor="nw", image=self.preview_photo
            )
        else:
            c.coords(self.preview_item, x1, y1)
            c.itemconfig(self.preview_item, image=self.preview_photo)
        c.tag_raise(self.preview_item)

        if self.rect_item is None:
            self.rect_item = c.create_rectangle(x1, y1, x2, y2, outline=BORDER, width=2)
        else:
            c.coords(self.rect_item, x1, y1, x2, y2)
        c.tag_raise(self.rect_item)

        real_w = int(round(w / self.scale))
        real_h = int(round(h / self.scale))
        label = "%d × %d" % (real_w, real_h)

        if self.size_bg is None:
            self.size_bg = c.create_rectangle(0, 0, 0, 0, fill="#000000", outline="")
            self.size_text = c.create_text(
                0, 0, text="", fill="#7df9ff", font=(FONT, 10, "bold"), anchor="nw"
            )
        tx = x1 + 6
        ty = y2 + 8 if y2 + 28 < self.canvas.winfo_height() else max(0, y1 - 26)
        c.coords(self.size_bg, tx - 5, ty - 3, tx + 7 * len(label) + 6, ty + 20)
        c.coords(self.size_text, tx, ty)
        c.itemconfig(self.size_text, text=label)
        c.tag_raise(self.size_bg)
        c.tag_raise(self.size_text)

    # -- eventos ------------------------------------------------------------ #
    def _clamp(self, x, y):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        return max(0, min(x, w - 1)), max(0, min(y, h - 1))

    def _reset_selection(self):
        for item in (self.preview_item, self.rect_item, self.size_bg, self.size_text):
            if item is not None:
                self.canvas.delete(item)
        self.preview_item = self.rect_item = None
        self.size_bg = self.size_text = None
        self.box = None

    def _on_press(self, event):
        self._clear_hint()
        self.start = (event.x, event.y)
        self._reset_selection()

    def _on_drag(self, event):
        if not self.start:
            return
        x1, y1 = self.start
        x2, y2 = self._clamp(event.x, event.y)
        bx1, by1 = min(x1, x2), min(y1, y2)
        bx2, by2 = max(x1, x2), max(y1, y2)
        self.box = (bx1, by1, bx2, by2)
        self._draw_selection(bx1, by1, bx2, by2)

    def _on_release(self, event):
        if not self.box:
            return
        bx1, by1, bx2, by2 = self.box
        if bx2 - bx1 < 4 or by2 - by1 < 4:
            self.box = None
        else:
            self.confirm()

    # -- resultado ---------------------------------------------------------- #
    def confirm(self):
        if not self.box:
            return
        x1, y1, x2, y2 = self.box
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        try:
            box = (
                max(0, int(round(x1 / self.scale))),
                max(0, int(round(y1 / self.scale))),
                min(self.image.width, int(round(x2 / self.scale))),
                min(self.image.height, int(round(y2 / self.scale))),
            )
            result = self.image.crop(box)
        except Exception:
            self.cancel()
            return
        self._close()
        self.on_confirm(result)

    def cancel(self):
        self._close()
        self.on_cancel()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# --------------------------------------------------------------------------- #
# Aplicacion
# --------------------------------------------------------------------------- #
class ScreenshotApp:
    def __init__(self, root, outdir=None, prefix="Captura"):
        self.root = root
        self.outdir = Path(outdir) if outdir else None
        self.prefix = prefix
        self.busy = False
        self.overlay = None
        self.last_path = None
        self.preview_ref = None
        self.events = queue.Queue()
        self._hotkey_thread_id = None
        self._after_id = None

        root.title(APP_NAME)
        root.configure(bg=BG)
        root.resizable(False, False)

        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        if IS_WINDOWS:
            self._start_hotkey_thread()
        else:
            self._bind_local_hotkeys()
        self._center()

    # -- interfaz ----------------------------------------------------------- #
    def _center(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry("+%d+%d" % (x, y))

    def _build_ui(self):
        pad = 16
        root = self.root

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=pad, pady=(pad, 0))

        tk.Label(
            header, text="Capturas", bg=BG, fg=FG,
            font=(FONT, 15, "bold"), anchor="w",
        ).pack(fill="x")

        tk.Label(
            header,
            text="Elige pantalla completa o recorta una zona.\n"
                 "Se guarda solo, en el Escritorio, con fecha y hora.",
            bg=BG, fg=MUTED, font=(FONT, 9), justify="left", anchor="w",
        ).pack(fill="x", pady=(2, 0))

        body = tk.Frame(root, bg=CARD, padx=14, pady=14)
        body.pack(fill="x", padx=pad, pady=(14, 0))

        self.btn_full = self._make_button(
            body, "Pantalla completa", "F1", lambda: self.capture("full"), primary=True,
        )
        self.btn_full.pack(fill="x")

        self.btn_crop = self._make_button(
            body, "Recortar zona", "F2", lambda: self.capture("crop"), primary=False,
        )
        self.btn_crop.pack(fill="x", pady=(10, 0))

        delay_row = tk.Frame(body, bg=CARD)
        delay_row.pack(fill="x", pady=(12, 0))
        tk.Label(
            delay_row, text="Retardo antes de capturar", bg=CARD, fg=MUTED,
            font=(FONT, 9),
        ).pack(side="left")
        self.delay_var = tk.StringVar(value="0")
        tk.Spinbox(
            delay_row, from_=0, to=10, width=3, textvariable=self.delay_var,
            justify="center", bg=GHOST, fg=FG, buttonbackground=GHOST,
            relief="flat", font=(FONT, 10), insertbackground=FG, highlightthickness=0,
        ).pack(side="right")
        tk.Label(
            delay_row, text="segundos", bg=CARD, fg=MUTED, font=(FONT, 9),
        ).pack(side="right", padx=(0, 6))

        info = tk.Frame(root, bg=BG)
        info.pack(fill="x", padx=pad, pady=(12, 0))
        self.hotkey_label = tk.Label(
            info,
            text=self._hotkey_text(),
            bg=BG, fg=MUTED, font=(FONT, 8), anchor="w", justify="left",
            wraplength=290,
        )
        self.hotkey_label.pack(fill="x")

        preview_card = tk.Frame(root, bg=CARD, padx=10, pady=10)
        preview_card.pack(fill="x", padx=pad, pady=(12, 0))

        self.preview_label = tk.Label(
            preview_card, text="Aun no hay capturas", bg=CARD, fg=MUTED,
            font=(FONT, 9), height=4,
        )
        self.preview_label.pack(fill="x")

        self.file_label = tk.Label(
            preview_card, text="Se guardara en: %s" % self._folder_name(),
            bg=CARD, fg=FG, font=(FONT, 8), anchor="w", wraplength=280, justify="left",
        )
        self.file_label.pack(fill="x", pady=(6, 0))

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill="x", padx=pad, pady=(12, pad))
        self._make_button(
            footer, "Abrir carpeta", None, self.open_folder, primary=False,
            small=True, width=15,
        ).pack(side="left")
        self._make_button(
            footer, "Salir", None, self.quit, primary=False, small=True, width=8,
        ).pack(side="right")

    def _make_button(self, parent, text, hint, command, primary, small=False, width=None):
        bg = ACCENT if primary else GHOST
        hover = ACCENT_HOVER if primary else GHOST_HOVER
        label = text if not hint else "%s   (%s)" % (text, hint)
        btn = tk.Button(
            parent, text=label, command=command, bg=bg,
            fg="#ffffff" if primary else FG,
            activebackground=hover, activeforeground="#ffffff",
            bd=0, relief="flat",
            font=(FONT, 10, "bold" if primary else "normal"),
            cursor="hand2", highlightthickness=0,
            pady=7 if small else 9, width=width or 0,
        )
        btn.bind("<Enter>", lambda e, b=btn, c=hover: b.configure(bg=c))
        btn.bind("<Leave>", lambda e, b=btn, c=bg: b.configure(bg=c))
        return btn

    def _hotkey_text(self):
        if IS_WINDOWS:
            return ("Atajos globales:  Ctrl+Alt+S  completa   ·   "
                    "Ctrl+Alt+R  recortar")
        return "Atajos:  F1  pantalla completa   ·   F2  recortar"

    def _folder_name(self):
        folder = self.outdir or desktop_dir()
        return str(folder)

    # -- capturas ----------------------------------------------------------- #
    def _delay(self):
        try:
            return max(0, min(10, int(float(self.delay_var.get()))))
        except Exception:
            return 0

    def capture(self, mode, delay=None):
        if self.busy:
            return
        self.busy = True
        if delay is None:
            delay = self._delay()
        self.root.withdraw()
        self.root.after(150, lambda: self._do_capture(mode, delay))

    def _do_capture(self, mode, delay):
        try:
            if delay:
                time.sleep(delay)
            img, bounds = grab_desktop()
        except Exception as exc:
            self._restore()
            messagebox.showerror(
                APP_NAME, "No se pudo capturar la pantalla:\n\n%s" % exc
            )
            return

        if mode == "full":
            self._finish(img)
        else:
            self.overlay = CropOverlay(
                self.root, img, bounds,
                on_confirm=self._finish, on_cancel=self._cancel_crop,
            )

    def _finish(self, img):
        self.overlay = None
        self._restore()
        try:
            path = save_capture(img, self.outdir, self.prefix)
        except Exception as exc:
            messagebox.showerror(APP_NAME, "No se pudo guardar la captura:\n\n%s" % exc)
            return
        self.last_path = path
        self.file_label.configure(text=str(path))
        self._show_preview(img)

    def _cancel_crop(self):
        self.overlay = None
        self._restore()

    def _restore(self):
        self.busy = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _show_preview(self, img):
        try:
            thumb = img.copy()
            thumb.thumbnail((280, 110), Image.LANCZOS)
            self.preview_ref = ImageTk.PhotoImage(thumb)
            self.preview_label.configure(image=self.preview_ref, text="", height=0)
        except Exception:
            pass

    def open_folder(self):
        open_folder(self.last_path.parent if self.last_path else (self.outdir or desktop_dir()))

    # -- atajos ------------------------------------------------------------- #
    def _bind_local_hotkeys(self):
        self.root.bind_all("<F1>", lambda e: self.capture("full"))
        self.root.bind_all("<F2>", lambda e: self.capture("crop"))
        self.root.bind_all("<Control-Alt-s>", lambda e: self.capture("full"))
        self.root.bind_all("<Control-Alt-r>", lambda e: self.capture("crop"))

    def _start_hotkey_thread(self):
        threading.Thread(
            target=_hotkey_worker, args=(self.events,), daemon=True
        ).start()
        self._drain_events()

    def _drain_events(self):
        if not self.root.winfo_exists():
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "ready":
                    failed, thread_id = payload
                    self._hotkey_thread_id = thread_id
                    if failed:
                        self.hotkey_label.configure(
                            text="Atajos globales no disponibles (%s). "
                                 "Usa F1 / F2 en esta ventana." % ", ".join(failed)
                        )
                elif kind == "hotkey":
                    mode = HOTKEY_MODES.get(payload)
                    if mode:
                        self.capture(mode)
        except queue.Empty:
            pass
        self._after_id = self.root.after(100, self._drain_events)

    def _stop_hotkey_thread(self):
        try:
            if self._hotkey_thread_id:
                ctypes.windll.user32.PostThreadMessageW(
                    self._hotkey_thread_id, WM_QUIT, 0, 0
                )
        except Exception:
            pass

    def quit(self):
        self._stop_hotkey_thread()
        try:
            if getattr(self, "_after_id", None):
                self.root.after_cancel(self._after_id)
        except Exception:
            pass
        self.root.destroy()


# --------------------------------------------------------------------------- #
# Arranque / linea de comandos
# --------------------------------------------------------------------------- #
def build_parser():
    parser = argparse.ArgumentParser(
        prog="capturas",
        description="Capturas de pantalla completas o recortadas, guardadas "
                    "automaticamente en el Escritorio con fecha y hora.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--full", action="store_true",
                       help="captura todo el escritorio, guarda y sale")
    group.add_argument("--crop", action="store_true",
                       help="abre directamente el recorte de zona")
    parser.add_argument("--delay", type=float, default=0, metavar="SEG",
                        help="segundos de espera antes de capturar (por defecto 0)")
    parser.add_argument("--outdir", type=Path, default=None, metavar="CARPETA",
                        help="carpeta destino (por defecto el Escritorio)")
    parser.add_argument("--prefix", default="Captura", metavar="TEXTO",
                        help="prefijo del archivo (por defecto Captura)")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + VERSION)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    enable_dpi_awareness()

    if args.full:
        if args.delay > 0:
            time.sleep(args.delay)
        try:
            img, _bounds = grab_desktop()
            path = save_capture(img, args.outdir, args.prefix)
        except Exception as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return 1
        print(path)
        return 0

    guard = single_instance_guard()
    if guard is None:
        return 1

    root = tk.Tk()
    try:
        if IS_WINDOWS:
            root.iconbitmap(default=str(resource_path("icon.ico")))
        else:
            root.iconphoto(True, tk.PhotoImage(file=str(resource_path("icon.png"))))
    except Exception:
        pass

    app = ScreenshotApp(root, outdir=args.outdir, prefix=args.prefix)
    if args.crop:
        root.after(500, lambda: app.capture("crop", delay=args.delay))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
