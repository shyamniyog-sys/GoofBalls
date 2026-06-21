import tkinter as tk
from tkinter import ttk
import threading
import winreg
from PIL import Image, ImageTk, ImageDraw
import os
import random
import time
import math
import webbrowser
import json
import pystray

# ---------------------------------------------------------------------------
SURPRISE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
SURPRISE_ANIM_SPEED = 0.5

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
TRAY_ICON_PATH = r"C:\Users\Naveed\Downloads\GB.ico"

DEFAULT_SETTINGS = {
    "always_on_top":        True,
    "start_on_boot":        False,
    "pet_size":             150,
    "opacity":              1.0,
    "active_pet":           "default",
    "anim_interval_wag":    6000,   # ms between auto-wag
    "anim_interval_tongue": 8000,   # ms between auto-tongue
}

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                merged = DEFAULT_SETTINGS.copy()
                merged.update(json.load(f))
                return merged
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Windows registry helpers
# ---------------------------------------------------------------------------
APP_NAME = "GoofBalls"
APP_PATH = os.path.abspath(__file__)

def set_start_on_boot(enabled: bool):
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    if enabled:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'pythonw "{APP_PATH}"')
    else:
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
    winreg.CloseKey(key)

def get_start_on_boot() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False

# ---------------------------------------------------------------------------
# Tray icon loader
# ---------------------------------------------------------------------------
def load_tray_icon():
    if os.path.exists(TRAY_ICON_PATH):
        return Image.open(TRAY_ICON_PATH).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    # fallback paw-print
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c    = (139, 90, 43, 255)
    draw.ellipse([16, 28, 48, 58], fill=c)
    draw.ellipse([8,  14, 24, 28], fill=c)
    draw.ellipse([26, 10, 38, 24], fill=c)
    draw.ellipse([40, 14, 56, 28], fill=c)
    return img


# ---------------------------------------------------------------------------
# Reusable custom-title-bar window helper
# ---------------------------------------------------------------------------
# Colour palette shared across all settings windows
C_BG       = "#FEFAF5"   # window background
C_TITLE    = "#3B1F0A"   # title bar bg
C_TITLE_FG = "#FFFFFF"   # title text / icons
C_ACCENT   = "#8B5A2B"   # buttons, active slider
C_ACCENT2  = "#D2B48C"   # secondary button, trough
C_TEXT     = "#3B1F0A"   # body text
C_SEP      = "#E8D5BC"   # separator
C_CHROMA   = "#010101"   # transparent chroma key for rounded shell

CORNER_R   = 16          # corner radius in pixels

FONT_TITLE = ("Segoe UI Semibold", 11)
FONT_LABEL = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)


def _draw_rounded_bg(canvas, w, h, r, title_h, title_color, body_color, accent_color):
    """
    Draw a rounded-rectangle window shape onto a Canvas.
    Top section = title_color, bottom = body_color, thin accent stripe between them.
    """
    # ── full rounded rect clipping mask (body colour) ──────────────
    canvas.create_arc(0,     0,     r*2, r*2, start=90,  extent=90,  fill=body_color,  outline="")
    canvas.create_arc(w-r*2, 0,     w,   r*2, start=0,   extent=90,  fill=body_color,  outline="")
    canvas.create_arc(0,     h-r*2, r*2, h,   start=180, extent=90,  fill=body_color,  outline="")
    canvas.create_arc(w-r*2, h-r*2, w,   h,   start=270, extent=90,  fill=body_color,  outline="")
    canvas.create_rectangle(r, 0, w-r, h,   fill=body_color, outline="")
    canvas.create_rectangle(0, r, w,   h-r, fill=body_color, outline="")

    # ── title bar overlay (top portion, flat bottom so corners show) ─
    canvas.create_arc(0,     0,     r*2, r*2, start=90, extent=90, fill=title_color, outline="")
    canvas.create_arc(w-r*2, 0,     w,   r*2, start=0,  extent=90, fill=title_color, outline="")
    canvas.create_rectangle(r,   0, w-r, title_h, fill=title_color, outline="")
    canvas.create_rectangle(0,   r, w,   title_h, fill=title_color, outline="")

    # ── accent stripe ───────────────────────────────────────────────
    canvas.create_rectangle(0, title_h, w, title_h+2, fill=accent_color, outline="")


def make_settings_window(parent, title_text, width, height):
    """
    Returns (win, body_frame).
    win        – transparent Toplevel acting as rounded shell
    body_frame – Frame inside the canvas for placing widgets
    """
    TITLE_H = 38

    # ── Outer transparent shell ──────────────────────────────────────
    win = tk.Toplevel(parent)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.config(bg=C_CHROMA)
    win.attributes("-transparentcolor", C_CHROMA)
    win.resizable(False, False)

    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")

    # ── Canvas that draws the rounded shape ─────────────────────────
    canvas = tk.Canvas(win, width=width, height=height,
                       bg=C_CHROMA, highlightthickness=0, bd=0)
    canvas.place(x=0, y=0)

    _draw_rounded_bg(canvas, width, height, CORNER_R,
                     TITLE_H, C_TITLE, C_BG, C_ACCENT)

    # ── Title label ─────────────────────────────────────────────────
    title_lbl = tk.Label(canvas, text=title_text, font=FONT_TITLE,
                         bg=C_TITLE, fg=C_TITLE_FG)
    canvas.create_window(14, TITLE_H // 2, anchor="w", window=title_lbl)

    # ── Close button ────────────────────────────────────────────────
    def _close():
        win.destroy()

    close_btn = tk.Label(canvas, text=" ✕ ", font=("Segoe UI", 11),
                         bg=C_TITLE, fg=C_TITLE_FG, cursor="hand2")
    canvas.create_window(width - 8, TITLE_H // 2, anchor="e", window=close_btn)
    close_btn.bind("<Enter>", lambda e: close_btn.config(bg="#C0392B"))
    close_btn.bind("<Leave>", lambda e: close_btn.config(bg=C_TITLE))
    close_btn.bind("<Button-1>", lambda e: _close())

    # ── Minimise button ─────────────────────────────────────────────
    def _minimise():
        win.overrideredirect(False)
        win.iconify()
        def _restore(ev=None):
            win.deiconify()
            win.overrideredirect(True)
        win.bind("<Map>", _restore)

    min_btn = tk.Label(canvas, text=" — ", font=("Segoe UI", 11),
                       bg=C_TITLE, fg=C_TITLE_FG, cursor="hand2")
    canvas.create_window(width - 44, TITLE_H // 2, anchor="e", window=min_btn)
    min_btn.bind("<Enter>", lambda e: min_btn.config(bg="#555555"))
    min_btn.bind("<Leave>", lambda e: min_btn.config(bg=C_TITLE))
    min_btn.bind("<Button-1>", lambda e: _minimise())

    # ── Drag via title bar area ──────────────────────────────────────
    _drag = {"x": 0, "y": 0}
    def _drag_start(e):
        _drag["x"] = e.x_root - win.winfo_x()
        _drag["y"] = e.y_root - win.winfo_y()
    def _drag_move(e):
        win.geometry(f"+{e.x_root-_drag['x']}+{e.y_root-_drag['y']}")

    # bind drag on canvas title area and on the title label itself
    for widget in (canvas, title_lbl):
        widget.bind("<ButtonPress-1>",  _drag_start)
        widget.bind("<B1-Motion>",       _drag_move)

    # ── Body frame placed inside canvas below title+accent ───────────
    BODY_TOP = TITLE_H + 2          # title height + accent stripe
    body_h   = height - BODY_TOP

    body = tk.Frame(canvas, bg=C_BG, width=width, height=body_h)
    canvas.create_window(0, BODY_TOP, anchor="nw", window=body)

    return win, body


def section_label(parent, text):
    """Bold section header with a separator underneath."""
    tk.Label(parent, text=text, font=("Segoe UI Semibold", 10),
             bg=C_BG, fg=C_ACCENT).pack(anchor="w", padx=16, pady=(14, 2))
    tk.Frame(parent, bg=C_SEP, height=1).pack(fill="x", padx=16, pady=(0, 6))


def row_frame(parent):
    f = tk.Frame(parent, bg=C_BG)
    f.pack(fill="x", padx=16, pady=4)
    return f


def styled_button(parent, text, command, primary=True):
    bg = C_ACCENT if primary else C_ACCENT2
    fg = "white"  if primary else C_TEXT
    btn = tk.Label(parent, text=text, font=FONT_LABEL,
                   bg=bg, fg=fg, cursor="hand2",
                   padx=18, pady=6, relief="flat")
    btn.bind("<Enter>", lambda e: btn.config(bg="#6B4420" if primary else "#C0A882"))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    btn.bind("<Button-1>", lambda e: command())
    return btn


def styled_check(parent, variable, text):
    """Custom-looking checkbutton (plain tkinter Checkbutton styled to match)."""
    return tk.Checkbutton(parent, text=text, variable=variable,
                          font=FONT_LABEL, bg=C_BG, fg=C_TEXT,
                          activebackground=C_BG, activeforeground=C_TEXT,
                          selectcolor=C_BG,
                          relief="flat", bd=0, cursor="hand2")


def styled_slider(parent, **kwargs):
    defaults = dict(
        orient="horizontal", length=200,
        bg=C_BG, troughcolor=C_ACCENT2,
        highlightthickness=0, sliderrelief="flat",
        activebackground=C_ACCENT, fg=C_ACCENT,
        bd=0, showvalue=False,
    )
    defaults.update(kwargs)
    return tk.Scale(parent, **defaults)


# ---------------------------------------------------------------------------
# DesktopPet
# ---------------------------------------------------------------------------
class DesktopPet:
    def __init__(self, root):
        self.root     = root
        self.settings = load_settings()
        self.pet_size = self.settings["pet_size"]
        self._settings_win     = None
        self._pet_settings_win = None

        # ── Window ──────────────────────────────────────────────────
        self.root.attributes("-topmost", self.settings["always_on_top"])
        self.root.overrideredirect(True)
        self.transparent_color = '#000001'
        self.root.config(bg=self.transparent_color)
        self.root.attributes("-transparentcolor", self.transparent_color)
        self.root.attributes("-alpha", self.settings["opacity"])

        # ── Frames ──────────────────────────────────────────────────
        self.base_dir  = os.path.dirname(os.path.abspath(__file__))
        self.pil_frames = {}
        self._load_all_frames()

        # ── State ───────────────────────────────────────────────────
        self.current_state  = "default"
        self.current_frame  = 0
        self.x = self.y     = 0
        self.is_dragging    = False
        self.action_count   = 0
        self.sleep_timer    = None
        self.context_menu   = None
        self.zzz_windows    = []
        self.zzz_timer      = None
        self.surprise_active = False

        # ── Movement / timing ───────────────────────────────────────
        self.walk_speed       = 5.5
        self.pos_x            = float(self.root.winfo_x())
        self.pos_y            = float(self.root.winfo_y())
        self.last_frame_time  = time.time()
        self.normal_anim_speed= 0.1
        self.walk_anim_speed  = 0.04
        self.bob_amplitude    = 8.0
        self.bob_frequency    = 18.0

        # ── Widget ──────────────────────────────────────────────────
        self.label = tk.Label(root, bg=self.transparent_color,
                              borderwidth=0, highlightthickness=0)
        self.label.pack()

        self.animate()
        self._schedule_wag()
        self._schedule_tongue()

        self.label.bind("<ButtonPress-1>",  self.start_move)
        self.label.bind("<B1-Motion>",       self.do_move)
        self.label.bind("<ButtonRelease-1>", self.stop_move)
        self.label.bind("<Button-3>",        self.show_context_menu)

        # ── System tray ─────────────────────────────────────────────
        self._tray_icon = None
        threading.Thread(target=self._run_tray, daemon=True).start()

    # ----------------------------------------------------------------
    # Auto-triggers  (rescheduled from settings)
    # ----------------------------------------------------------------
    def _schedule_wag(self):
        interval = self.settings.get("anim_interval_wag", 6000)
        self._wag_after_id = self.root.after(interval, self._trigger_wag)

    def _trigger_wag(self):
        if self.current_state == "default":
            self.current_state = "wagging"
            self.current_frame = 0
            self.action_count  = 0
        self._schedule_wag()

    def _schedule_tongue(self):
        interval = self.settings.get("anim_interval_tongue", 8000)
        self._tongue_after_id = self.root.after(interval, self._trigger_tongue)

    def _trigger_tongue(self):
        if self.current_state == "default":
            self.current_state = "tongue"
            self.current_frame = 0
            self.action_count  = 0
        self._schedule_tongue()

    # kept for compatibility
    def check_and_trigger_wagging(self): pass
    def check_and_trigger_tongue(self):  pass

    # ----------------------------------------------------------------
    # Frame loading
    # ----------------------------------------------------------------
    def _load_all_frames(self):
        sz = self.pet_size
        self.frames = {
            "default":       self.load_frames("DEFAULT",  size=sz),
            "wagging":       self.load_frames("WAGGING",  size=sz),
            "lift":          self.load_frames("Lift",     size=sz),
            "hi":            self.load_frames("Hi",       size=sz),
            "tongue":        self.load_frames("TONGUE",   size=sz),
            "pat_pat":       self.load_frames("pat-pat",  size=sz),
            "walking_left":  self.load_walking_sprite("WALKING", "LEFT.png",  "walking_left",  size=sz),
            "walking_right": self.load_walking_sprite("WALKING", "RIGHT.png", "walking_right", size=sz),
            "sleeping":      self.load_frames("Sleeping", size=sz, save_pil_key="sleeping"),
            "surprise":      self.load_surprise_frames(
                                 os.path.join(self.base_dir, "RandomWebiste"), size=sz),
        }

    def _reload_frames(self):
        self.pil_frames = {}
        self._load_all_frames()
        self.current_state = "default"
        self.current_frame = 0

    def load_frames(self, folder_path, flip=False, save_pil_key=None, size=150):
        frames, pil_list = [], []
        if not os.path.isabs(folder_path):
            folder_path = os.path.join(self.base_dir, folder_path)
        if not os.path.isdir(folder_path):
            return frames
        for file in sorted(f for f in os.listdir(folder_path) if f.endswith(".png")):
            img = Image.open(os.path.join(folder_path, file)).convert("RGBA").resize(
                (size, size), Image.Resampling.LANCZOS)
            if flip:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            img.putalpha(img.split()[-1].point(lambda p: 255 if p > 128 else 0))
            frames.append(ImageTk.PhotoImage(img))
            pil_list.append(img)
        if save_pil_key:
            self.pil_frames[save_pil_key] = pil_list
        return frames

    def load_walking_sprite(self, folder_path, filename, pil_key, size=150):
        frames, pil_list = [], []
        if not os.path.isabs(folder_path):
            folder_path = os.path.join(self.base_dir, folder_path)
        path = os.path.join(folder_path, filename)
        if os.path.isfile(path):
            img = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            img.putalpha(img.split()[-1].point(lambda p: 255 if p > 128 else 0))
            frames.append(ImageTk.PhotoImage(img))
            pil_list.append(img)
        if pil_key:
            self.pil_frames[pil_key] = pil_list
        return frames

    def load_surprise_frames(self, folder_path, size=150):
        frames = []
        if not os.path.isdir(folder_path):
            return frames
        for file in sorted(f for f in os.listdir(folder_path)
                           if os.path.splitext(f)[1].lower() in SURPRISE_IMAGE_EXTENSIONS):
            img = Image.open(os.path.join(folder_path, file)).convert("RGBA").resize(
                (size, size), Image.Resampling.LANCZOS)
            img.putalpha(img.split()[-1].point(lambda p: 255 if p > 128 else 0))
            frames.append(ImageTk.PhotoImage(img))
        return frames

    def set_walk_sprite_for_direction(self, from_x, to_x):
        self.walk_sprite_key = "walking_left" if to_x < from_x else "walking_right"

    def _discover_pets(self):
        pets = []
        for name in sorted(os.listdir(self.base_dir)):
            full = os.path.join(self.base_dir, name)
            if os.path.isdir(full) and not name.startswith((".", "_")):
                if any(f.lower().endswith(".png") for f in os.listdir(full)):
                    pets.append(name)
        return pets or ["default"]


    # ----------------------------------------------------------------
    # System tray
    # ----------------------------------------------------------------
    def _run_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Settings",     self._tray_open_settings),
            pystray.MenuItem("Pet Settings", self._tray_open_pet_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",         self._tray_exit),
        )
        self._tray_icon = pystray.Icon(APP_NAME, load_tray_icon(), APP_NAME, menu)
        self._tray_icon.run()

    def _tray_open_settings(self, *_):
        self.root.after(0, self.open_settings_window)

    def _tray_open_pet_settings(self, *_):
        self.root.after(0, self.open_pet_settings_window)

    def _tray_exit(self, *_):
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ----------------------------------------------------------------
    # App Settings window
    # ----------------------------------------------------------------
    def open_settings_window(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return

        win, body = make_settings_window(self.root, "  GoofBalls  —  Settings", 360, 260)
        self._settings_win = win

        # ── Always on top ──────────────────────────────────────────
        section_label(body, "Display")
        r1 = row_frame(body)
        aot_var = tk.BooleanVar(value=self.settings["always_on_top"])
        styled_check(r1, aot_var, "Always on top").pack(side="left")

        # ── Start on boot ──────────────────────────────────────────
        r2 = row_frame(body)
        boot_var = tk.BooleanVar(value=get_start_on_boot())
        styled_check(r2, boot_var, "Start on boot  (adds to Windows startup)").pack(side="left")

        # ── Buttons ────────────────────────────────────────────────
        tk.Frame(body, bg=C_SEP, height=1).pack(fill="x", padx=16, pady=(14, 0))
        btn_row = tk.Frame(body, bg=C_BG)
        btn_row.pack(pady=12)

        _orig_aot  = self.settings["always_on_top"]
        _orig_boot = get_start_on_boot()

        def _apply():
            self.settings["always_on_top"] = aot_var.get()
            self.settings["start_on_boot"] = boot_var.get()
            self.root.attributes("-topmost", aot_var.get())
            set_start_on_boot(boot_var.get())
            save_settings(self.settings)
            apply_btn.config(text="Saved ✓")
            win.after(800, win.destroy)

        def _cancel():
            # revert any live changes
            self.root.attributes("-topmost", _orig_aot)
            win.destroy()

        apply_btn = styled_button(btn_row, "Apply", _apply, primary=True)
        apply_btn.pack(side="left", padx=6)
        styled_button(btn_row, "Cancel", _cancel, primary=False).pack(side="left", padx=6)

    # ----------------------------------------------------------------
    # Pet Settings window
    # ----------------------------------------------------------------
    def open_pet_settings_window(self):
        if self._pet_settings_win and self._pet_settings_win.winfo_exists():
            self._pet_settings_win.lift()
            return

        win, body = make_settings_window(self.root, "  GoofBalls  —  Pet Settings", 420, 500)
        self._pet_settings_win = win

        # snapshot of values when window opened (for Cancel / revert)
        _orig_size    = self.settings["pet_size"]
        _orig_opacity = self.settings["opacity"]
        _orig_pet     = self.settings["active_pet"]
        _orig_wag     = self.settings["anim_interval_wag"]
        _orig_tongue  = self.settings["anim_interval_tongue"]

        # ── Appearance ─────────────────────────────────────────────
        section_label(body, "Appearance")

        # Size
        r_size = row_frame(body)
        tk.Label(r_size, text="Size", font=FONT_LABEL, bg=C_BG,
                 fg=C_TEXT, width=10, anchor="w").pack(side="left")
        size_var   = tk.IntVar(value=self.settings["pet_size"])
        size_val_lbl = tk.Label(r_size, text=f"{size_var.get()} px",
                                font=FONT_LABEL, bg=C_BG, fg=C_ACCENT, width=7)
        size_val_lbl.pack(side="right")

        def _on_size(val):
            v = int(float(val))
            size_val_lbl.config(text=f"{v} px")
            # live preview — reload is expensive so debounce with after_cancel
            if hasattr(win, "_size_job"):
                win.after_cancel(win._size_job)
            win._size_job = win.after(300, lambda: self._live_resize(v))

        styled_slider(body, from_=80, to=300, variable=size_var,
                      command=_on_size).pack(fill="x", padx=16, pady=(0, 6))

        # Opacity
        r_op = row_frame(body)
        tk.Label(r_op, text="Opacity", font=FONT_LABEL, bg=C_BG,
                 fg=C_TEXT, width=10, anchor="w").pack(side="left")
        opacity_var   = tk.DoubleVar(value=round(self.settings["opacity"] * 100))
        opacity_val_lbl = tk.Label(r_op, text=f"{int(opacity_var.get())}%",
                                   font=FONT_LABEL, bg=C_BG, fg=C_ACCENT, width=7)
        opacity_val_lbl.pack(side="right")

        def _on_opacity(val):
            v = int(float(val))
            opacity_val_lbl.config(text=f"{v}%")
            self.root.attributes("-alpha", v / 100.0)   # live

        styled_slider(body, from_=20, to=100, variable=opacity_var,
                      command=_on_opacity).pack(fill="x", padx=16, pady=(0, 6))


        # ── Active pet ─────────────────────────────────────────────
        section_label(body, "Active Pet")
        r_pet = row_frame(body)
        tk.Label(r_pet, text="Pet skin", font=FONT_LABEL, bg=C_BG,
                 fg=C_TEXT, width=10, anchor="w").pack(side="left")
        pet_var     = tk.StringVar(value=self.settings["active_pet"])
        pet_options = self._discover_pets()
        pet_cb = ttk.Combobox(r_pet, textvariable=pet_var, values=pet_options,
                              state="readonly", width=18, font=FONT_LABEL)
        pet_cb.pack(side="left", padx=6)

        # Style the combobox to match the palette
        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=C_BG, background=C_ACCENT2,
                        foreground=C_TEXT, selectbackground=C_ACCENT,
                        selectforeground="white")

        # ── Animation intervals ────────────────────────────────────
        section_label(body, "Animation Intervals")

        # Wag interval
        r_wag = row_frame(body)
        tk.Label(r_wag, text="Tail wag", font=FONT_LABEL, bg=C_BG,
                 fg=C_TEXT, width=10, anchor="w").pack(side="left")
        wag_var   = tk.IntVar(value=self.settings["anim_interval_wag"] // 1000)
        wag_val_lbl = tk.Label(r_wag, text=f"{wag_var.get()} s",
                               font=FONT_LABEL, bg=C_BG, fg=C_ACCENT, width=7)
        wag_val_lbl.pack(side="right")

        def _on_wag(val):
            wag_val_lbl.config(text=f"{int(float(val))} s")

        styled_slider(body, from_=2, to=30, variable=wag_var,
                      command=_on_wag).pack(fill="x", padx=16, pady=(0, 6))

        # Tongue interval
        r_tongue = row_frame(body)
        tk.Label(r_tongue, text="Tongue out", font=FONT_LABEL, bg=C_BG,
                 fg=C_TEXT, width=10, anchor="w").pack(side="left")
        tongue_var   = tk.IntVar(value=self.settings["anim_interval_tongue"] // 1000)
        tongue_val_lbl = tk.Label(r_tongue, text=f"{tongue_var.get()} s",
                                  font=FONT_LABEL, bg=C_BG, fg=C_ACCENT, width=7)
        tongue_val_lbl.pack(side="right")

        def _on_tongue(val):
            tongue_val_lbl.config(text=f"{int(float(val))} s")

        styled_slider(body, from_=2, to=60, variable=tongue_var,
                      command=_on_tongue).pack(fill="x", padx=16, pady=(0, 6))

        # ── Buttons ────────────────────────────────────────────────
        tk.Frame(body, bg=C_SEP, height=1).pack(fill="x", padx=16, pady=(14, 0))
        btn_row = tk.Frame(body, bg=C_BG)
        btn_row.pack(pady=12)

        def _apply():
            new_size    = size_var.get()
            new_opacity = opacity_var.get() / 100.0
            new_pet     = pet_var.get()
            new_wag     = wag_var.get() * 1000
            new_tongue  = tongue_var.get() * 1000

            frames_changed = (new_size != self.settings["pet_size"] or
                              new_pet  != self.settings["active_pet"])

            self.settings.update({
                "pet_size":             new_size,
                "opacity":              new_opacity,
                "active_pet":           new_pet,
                "anim_interval_wag":    new_wag,
                "anim_interval_tongue": new_tongue,
            })
            save_settings(self.settings)

            self.pet_size = new_size
            self.root.attributes("-alpha", new_opacity)
            if frames_changed:
                self._reload_frames()

            apply_btn.config(text="Saved ✓")
            win.after(800, win.destroy)

        def _cancel():
            # revert live previews
            self.root.attributes("-alpha", _orig_opacity)
            if self.pet_size != _orig_size:
                self.pet_size = _orig_size
                self._reload_frames()
            win.destroy()

        apply_btn = styled_button(btn_row, "Apply", _apply, primary=True)
        apply_btn.pack(side="left", padx=6)
        styled_button(btn_row, "Cancel", _cancel, primary=False).pack(side="left", padx=6)

    # ----------------------------------------------------------------
    # Live resize helper (debounced from size slider)
    # ----------------------------------------------------------------
    def _live_resize(self, new_size):
        if new_size == self.pet_size:
            return
        self.pet_size = new_size
        self._reload_frames()


    # ----------------------------------------------------------------
    # Right-click context menu
    # ----------------------------------------------------------------
    def show_context_menu(self, event):
        self.close_context_menu()

        self.context_menu = tk.Toplevel(self.root)
        self.context_menu.overrideredirect(True)
        tc = '#000002'
        self.context_menu.config(bg=tc)
        self.context_menu.attributes("-transparentcolor", tc)
        self.context_menu.attributes("-topmost", True)
        self.context_menu.geometry(f"+{event.x_root}+{event.y_root}")

        item_height = 35
        width       = 148
        menu_items  = [("Sleep", self.on_sleep_click)]
        if not self.is_asleep():
            menu_items.append(("Surprise me!", self.on_surprise_click))
        menu_items += [
            ("Pet Settings", lambda: (self.close_context_menu(), self.open_pet_settings_window())),
            ("Settings",     lambda: (self.close_context_menu(), self.open_settings_window())),
        ]
        height = item_height * len(menu_items)
        r      = 12

        canvas = tk.Canvas(self.context_menu, width=width, height=height,
                           bg=tc, highlightthickness=0)
        canvas.pack()
        bg = "#D2B48C"
        for ox, oy in [(0,0),(width-r*2,0),(0,height-r*2),(width-r*2,height-r*2)]:
            canvas.create_oval(ox, oy, ox+r*2, oy+r*2, fill=bg, outline="")
        canvas.create_rectangle(r, 0, width-r, height, fill=bg, outline="")
        canvas.create_rectangle(0, r, width, height-r, fill=bg, outline="")

        for idx, (lbl_text, cmd) in enumerate(menu_items):
            item = tk.Label(canvas, text=lbl_text, bg=bg, fg="#4A2F13",
                            font=("Segoe UI", 10), cursor="hand2")
            canvas.create_window(width // 2, item_height // 2 + idx * item_height, window=item)
            item.bind("<Enter>", lambda e, w=item: w.config(bg="#8B5A2B", fg="white"))
            item.bind("<Leave>", lambda e, w=item: w.config(bg=bg, fg="#4A2F13"))
            item.bind("<Button-1>", lambda e, c=cmd: c())

        self.context_menu.focus_set()
        self.context_menu.bind("<FocusOut>", lambda e: self.close_context_menu())
        self.root.bind("<ButtonPress-1>", lambda e: self.close_context_menu(), add="+")

    def close_context_menu(self):
        if self.context_menu:
            try:
                self.context_menu.destroy()
            except Exception:
                pass
            self.context_menu = None

    # ----------------------------------------------------------------
    # Sleep / Surprise
    # ----------------------------------------------------------------
    def is_asleep(self):
        return self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]

    def on_sleep_click(self):
        self.close_context_menu()
        if self.current_state in ["walking_down", "sleeping_phase1",
                                   "sleeping_phase2", "sleeping_phase3", "walking_up"]:
            return
        self.start_sleep_flow()

    def on_surprise_click(self):
        self.close_context_menu()
        if self.is_asleep() or self.surprise_active:
            return
        self.start_surprise_flow()

    def load_random_website_url(self):
        p = os.path.join(self.base_dir, "Random Websites.txt")
        with open(p, "r", encoding="utf-8") as f:
            urls = [l.strip() for l in f if l.strip()]
        if not urls:
            raise ValueError("No URLs found")
        return random.choice(urls)

    def start_surprise_flow(self):
        if not self.frames.get("surprise"):
            self.finish_surprise_flow()
            return
        self.surprise_active = True
        self.current_state   = "surprise"
        self.current_frame   = 0
        self.action_count    = 0

    def finish_surprise_flow(self):
        try:
            webbrowser.open(self.load_random_website_url())
        except Exception:
            pass
        finally:
            self.surprise_active = False

    # ----------------------------------------------------------------
    # Sleep flow
    # ----------------------------------------------------------------
    def start_sleep_flow(self):
        sw, sh  = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        cx      = self.root.winfo_x()
        self.walk_target_x = 0 if cx >= sw / 2 else sw - self.pet_size
        self.walk_target_y = sh - self.pet_size
        self.set_walk_sprite_for_direction(cx, self.walk_target_x)
        self.pos_x, self.pos_y = float(cx), float(self.root.winfo_y())
        self.current_state = "walking_down"
        self.current_frame = 0

    def fade_transition(self, start_pil, end_pil, duration_ms, callback):
        steps    = 15
        interval = duration_ms // steps
        def step(n):
            if self.current_state not in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
                return
            if n > steps:
                callback(); return
            b = Image.blend(start_pil, end_pil, n / steps)
            b.putalpha(b.split()[-1].point(lambda p: 255 if p > 128 else 0))
            self.fade_photo = ImageTk.PhotoImage(b)
            self.label.config(image=self.fade_photo)
            self.root.after(interval, lambda: step(n + 1))
        step(0)

    def enter_sleep_state(self):
        if self.sleep_timer: self.root.after_cancel(self.sleep_timer)
        self.current_state = "sleeping_phase1"
        self.current_frame = 0
        wk  = getattr(self, "walk_sprite_key", "walking_right")
        self.fade_transition(self.pil_frames[wk][0], self.pil_frames["sleeping"][0], 800,
            lambda: setattr(self, "sleep_timer", self.root.after(2200, self.enter_sleep_phase2)))

    def enter_sleep_phase2(self):
        self.current_state = "sleeping_phase2"; self.current_frame = 1
        self.fade_transition(self.pil_frames["sleeping"][0], self.pil_frames["sleeping"][1], 800,
            lambda: setattr(self, "sleep_timer", self.root.after(4200, self.enter_sleep_phase3)))

    def enter_sleep_phase3(self):
        self.current_state = "sleeping_phase3"; self.current_frame = 2; self.sleep_timer = None
        self.fade_transition(self.pil_frames["sleeping"][1], self.pil_frames["sleeping"][2],
                             800, self.start_zzz_loop)


    # ----------------------------------------------------------------
    # ZZZ
    # ----------------------------------------------------------------
    def start_zzz_loop(self):
        if self.current_state != "sleeping_phase3": return
        self.zzz_windows = []
        self.spawn_zzz()

    def spawn_zzz(self):
        if self.current_state != "sleeping_phase3": return
        z_win = tk.Toplevel(self.root)
        z_win.overrideredirect(True)
        z_bg = '#000001'
        z_win.config(bg=z_bg)
        z_win.attributes("-transparentcolor", z_bg)
        z_win.attributes("-topmost", True)
        lbl = tk.Label(z_win,
                       text=random.choice(["z","Z","zZ"]),
                       bg=z_bg,
                       fg=random.choice(["#9370DB","#8A2BE2","#4B0082","#A0522D","#5C4033"]),
                       font=("Comic Sans MS", random.randint(10,16), "bold"))
        lbl.pack()
        rx = self.root.winfo_x() + 45 + random.randint(-15, 15)
        ry = self.root.winfo_y() + 25 + random.randint(-10, 10)
        z_win.geometry(f"+{rx}+{ry}")
        self.zzz_windows.append(z_win)

        def drift(win, x, y, age=0):
            if self.current_state != "sleeping_phase3" or win not in self.zzz_windows:
                try: win.destroy()
                except: pass
                if win in self.zzz_windows: self.zzz_windows.remove(win)
                return
            if age > 40:
                try: win.destroy()
                except: pass
                if win in self.zzz_windows: self.zzz_windows.remove(win)
                return
            ny, nx = y-3, x + int(random.choice([-2,-1,0,1,2]))
            try: win.geometry(f"+{nx}+{ny}")
            except: return
            self.root.after(50, lambda: drift(win, nx, ny, age+1))
        drift(z_win, rx, ry)
        self.zzz_timer = self.root.after(1200, self.spawn_zzz)

    def cleanup_zzz(self):
        if hasattr(self,"zzz_timer") and self.zzz_timer:
            try: self.root.after_cancel(self.zzz_timer)
            except: pass
            self.zzz_timer = None
        for w in getattr(self, "zzz_windows", []):
            try: w.destroy()
            except: pass
        self.zzz_windows = []

    # ----------------------------------------------------------------
    # Wake up
    # ----------------------------------------------------------------
    def wake_up(self):
        self.cleanup_zzz()
        if self.sleep_timer:
            self.root.after_cancel(self.sleep_timer)
            self.sleep_timer = None
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        min_x  = int(sw * 0.6)
        max_x  = max(min_x+1, int(sw*0.9) - self.pet_size)
        self.walk_target_x = random.randint(min_x, max_x)
        min_y  = 10
        max_y  = max(min_y+1, int(sh*0.6) - self.pet_size)
        self.walk_target_y = random.randint(min_y, max_y)
        self.set_walk_sprite_for_direction(self.root.winfo_x(), self.walk_target_x)
        self.pos_x = float(self.root.winfo_x())
        self.pos_y = float(self.root.winfo_y())
        self.current_state = "walking_up"
        self.current_frame = 0

    # ----------------------------------------------------------------
    # Animation loop
    # ----------------------------------------------------------------
    def animate(self):
        fk = self.current_state
        if self.current_state in ["walking_down","walking_up"]:
            fk = getattr(self,"walk_sprite_key","walking_right")
        elif self.current_state in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
            fk = "sleeping"

        sf = self.frames.get(fk)
        if sf:
            if   self.current_state == "sleeping_phase1": self.current_frame = 0
            elif self.current_state == "sleeping_phase2": self.current_frame = 1
            elif self.current_state == "sleeping_phase3": self.current_frame = 2

            if self.current_state not in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
                self.label.config(image=sf[self.current_frame])

            delay = (self.walk_anim_speed if self.current_state in ["walking_down","walking_up"]
                     else SURPRISE_ANIM_SPEED if self.current_state == "surprise"
                     else self.normal_anim_speed)

            now = time.time()
            if now - self.last_frame_time >= delay:
                self.last_frame_time = now
                if self.current_state in ["wagging","hi","tongue","pat_pat","surprise"]:
                    if self.current_frame < len(sf)-1:
                        self.current_frame += 1
                    else:
                        self.current_frame  = 0
                        self.action_count  += 1
                        limit = {"wagging":5,"hi":6,"pat_pat":5}.get(self.current_state, 1)
                        if self.action_count >= limit:
                            if self.current_state == "surprise":
                                self.finish_surprise_flow()
                            self.current_state = "default"
                            self.action_count  = 0
                elif self.current_state not in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
                    self.current_frame = (self.current_frame+1) % len(sf)

            if self.current_state in ["walking_down","walking_up"]:
                dx, dy = self.walk_target_x-self.pos_x, self.walk_target_y-self.pos_y
                dist   = (dx**2+dy**2)**0.5
                if dist > self.walk_speed:
                    self.pos_x += (dx/dist)*self.walk_speed
                    self.pos_y += (dy/dist)*self.walk_speed
                    bob = math.sin(time.time()*self.bob_frequency)*self.bob_amplitude
                    self.root.geometry(f"+{round(self.pos_x)}+{round(self.pos_y+bob)}")
                else:
                    self.root.geometry(f"+{self.walk_target_x}+{self.walk_target_y}")
                    self.pos_x, self.pos_y = float(self.walk_target_x), float(self.walk_target_y)
                    if self.current_state == "walking_down":
                        self.enter_sleep_state()
                    else:
                        self.current_state = "default"; self.current_frame = 0

        self.root.after(16, self.animate)

    # ----------------------------------------------------------------
    # Drag handlers
    # ----------------------------------------------------------------
    def start_move(self, event):
        if self.current_state in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
            self.x, self.y = event.x, event.y; self.is_dragging = False; return
        if self.current_state in ["walking_down","walking_up","surprise"]: return
        self.x, self.y = event.x, event.y; self.is_dragging = False

    def do_move(self, event):
        if self.current_state in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
            self.is_dragging = True
            x = self.root.winfo_x()+(event.x-self.x)
            self.root.geometry(f"+{x}+{self.root.winfo_y()}")
            self.pos_x = float(x); return
        if self.current_state in ["walking_down","walking_up","surprise"]: return
        if not self.is_dragging:
            self.is_dragging = True; self.current_state = "lift"; self.current_frame = 0
        x = self.root.winfo_x()+(event.x-self.x)
        y = self.root.winfo_y()+(event.y-self.y)
        self.root.geometry(f"+{x}+{y}")
        self.pos_x, self.pos_y = float(x), float(y)

    def stop_move(self, event):
        if self.current_state in ["sleeping_phase1","sleeping_phase2","sleeping_phase3"]:
            if self.current_state == "sleeping_phase3" and not self.is_dragging:
                self.wake_up()
            self.is_dragging = False; return
        if self.current_state in ["walking_down","walking_up","surprise"]: return
        if not self.is_dragging and self.current_state == "default":
            self.current_state = "pat_pat" if random.choice([True,False]) else "hi"
            self.current_frame = 0; self.action_count = 0
        else:
            self.current_state = "default"; self.current_frame = 0
        self.is_dragging = False


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    pet_app = DesktopPet(root)
    root.mainloop()
