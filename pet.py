import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk, ImageGrab
import os
import random
import time
import math
import webbrowser
import threading
import warnings
import tkinter.font as tkfont
import traceback

warnings.filterwarnings("ignore")

SURPRISE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
SURPRISE_ANIM_SPEED = 0.5

# ---- PaddleOCR availability check (graceful degradation) ----
PADDLE_AVAILABLE = False
try:
    from paddleocr import PaddleOCR
    import cv2
    import numpy as np
    PADDLE_AVAILABLE = True
except Exception:
    PADDLE_AVAILABLE = False
    cv2 = None
    np = None


# =====================================================================
# OCR ENGINE — Handles all PaddleOCR API traps and C++ memory leak bugs
# =====================================================================
class OCREngine:
    """Wraps PaddleOCR with strict type-checking to avoid API pitfalls."""

    def __init__(self):
        self.available = PADDLE_AVAILABLE
        self.ocr = None
        if not self.available:
            return
        try:
            self.ocr = PaddleOCR(
                use_textline_orientation=True, 
                lang='en', 
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False
            )
        except Exception as e:
            print(f"PaddleOCR Init Failed: {e}")
            try:
                self.ocr = PaddleOCR(
                    lang='en', 
                    enable_mkldnn=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False
                )
            except Exception as e2:
                print(f"PaddleOCR Fallback Init Failed: {e2}")
                self.ocr = None
                self.available = False

    def get_clipboard_image(self):
        """Retrieve image from clipboard. Handles PIL Image, file path list, or None."""
        try:
            grabbed = ImageGrab.grabclipboard()
            if grabbed is None:
                return None
            if isinstance(grabbed, Image.Image):
                return grabbed
            if isinstance(grabbed, list) and len(grabbed) > 0:
                path = grabbed[0]
                if isinstance(path, str):
                    ext = os.path.splitext(path)[1].lower()
                    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"):
                        return Image.open(path)
            return None
        except Exception as e:
            print(f"Clipboard Error: {e}")
            return None

    def _extract_text(self, pil_image):
        import tempfile
        tmp_path = None
        try:
            if self.ocr is None:
                return ""
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
                
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            pil_image.save(tmp_path, format="PNG")
            
            raw = self.ocr.ocr(tmp_path)
            
            collected = []
            if raw is None:
                return ""
                
            if isinstance(raw, dict):
                raw = [raw]
                
            if not isinstance(raw, (list, tuple)):
                return ""

            for page in raw:
                if isinstance(page, dict):
                    texts = page.get("rec_texts", [])
                    if isinstance(texts, str):
                        texts = [texts]
                    for txt in texts:
                        if isinstance(txt, str):
                            if '<' in txt and '>' in txt and '::' in txt:
                                continue
                            if txt.strip():
                                collected.append(txt)
                                
                elif isinstance(page, (list, tuple)):
                    for item in page:
                        if not isinstance(item, (list, tuple)):
                            continue
                        if len(item) < 2:
                            continue
                        text_info = item[1]
                        if isinstance(text_info, (list, tuple)) and len(text_info) >= 1:
                            txt = text_info[0]
                        elif isinstance(text_info, str):
                            txt = text_info
                        else:
                            continue
                        if not isinstance(txt, str):
                            continue
                        if '<' in txt and '>' in txt and '::' in txt:
                            continue
                        if txt.strip():
                            collected.append(txt)
            return " ".join(collected)
            
        except Exception as e:
            print("========== OCR ERROR ==========")
            traceback.print_exc()
            print("================================")
            raise e
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except:
                    pass

    def process_image(self, callback):
        """Run clipboard retrieval and OCR entirely in a daemon thread."""
        def worker():
            text = ""
            error = None
            img = self.get_clipboard_image()
            
            if img is None:
                callback("", "No image detected!")
                return
                
            try:
                text = self._extract_text(img)
                if not text:
                    error = "No readable text found."
            except Exception as e:
                error = f"OCR Error: {type(e).__name__}"
                
            try:
                callback(text, error)
            except Exception:
                pass
                
        t = threading.Thread(target=worker, daemon=True)
        t.start()


# =====================================================================
# RETRO OCR UI — Speech bubble + result popup with pixel-art styling
# =====================================================================
class RetroOcrUI:
    """Manages retro-styled speech bubbles and result popups."""

    BG_COLOR = "#FFF8DC"      
    BORDER_COLOR = "#4A2F13"  
    ACCENT_COLOR = "#D2B48C"  

    def __init__(self, root):
        self.root = root
        self.bubble = None
        self.bubble_canvas = None
        self.bubble_label = None
        self.result_popup = None
        self.pet_x = 0
        self.pet_y = 0
        self._bubble_after = None
        self.font_name = self._pick_font()

    def _pick_font(self):
        try:
            available = tkfont.families()
        except Exception:
            available = []
        for candidate in ["Press Start 2P", "VT323", "Pixelated", "Courier New"]:
            if candidate in available:
                return candidate
        return "Courier New"

    def update_pet_pos(self, x, y):
        self.pet_x = x
        self.pet_y = y
        if self.bubble:
            self._position_bubble()

    def show_bubble(self, text, duration=None):
        self.hide_bubble()

        self.bubble = tk.Toplevel(self.root)
        self.bubble.overrideredirect(True)
        self.bubble.config(bg=self.BG_COLOR)
        self.bubble.attributes("-topmost", True)

        measure = tk.Label(self.bubble, text=text, bg=self.BG_COLOR, fg=self.BORDER_COLOR,
                           font=(self.font_name, 10, "bold"), padx=14, pady=8)
        measure.update_idletasks()
        lw = measure.winfo_reqwidth()
        lh = measure.winfo_reqheight()
        measure.destroy()

        border_w = 3
        pad = 4
        total_w = lw + pad * 2
        total_h = lh + pad * 2

        self.bubble_canvas = tk.Canvas(self.bubble, width=total_w, height=total_h,
                                       bg=self.BG_COLOR, highlightthickness=0, bd=0)
        self.bubble_canvas.pack()
        self.bubble_canvas.create_rectangle(
            border_w // 2, border_w // 2,
            total_w - border_w // 2, total_h - border_w // 2,
            outline=self.BORDER_COLOR, width=border_w
        )
        self.bubble_label = tk.Label(self.bubble_canvas, text=text, bg=self.BG_COLOR,
                                     fg=self.BORDER_COLOR, font=(self.font_name, 10, "bold"))
        self.bubble_canvas.create_window(total_w // 2, total_h // 2, window=self.bubble_label)

        self._position_bubble()

        if duration:
            if self._bubble_after:
                try:
                    self.root.after_cancel(self._bubble_after)
                except Exception:
                    pass
            self._bubble_after = self.root.after(duration, self.hide_bubble)

    def _position_bubble(self):
        if not self.bubble:
            return
        self.bubble.update_idletasks()
        w = self.bubble.winfo_reqwidth()
        h = self.bubble.winfo_reqheight()
        x = self.pet_x + 75 - w // 2
        y = self.pet_y - h - 8
        if y < 0:
            y = self.pet_y + 150 + 8
        if x < 0:
            x = 0
        screen_w = self.root.winfo_screenwidth()
        if x + w > screen_w:
            x = screen_w - w
        try:
            self.bubble.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def hide_bubble(self):
        if self._bubble_after:
            try:
                self.root.after_cancel(self._bubble_after)
            except Exception:
                pass
            self._bubble_after = None
        if self.bubble:
            try:
                self.bubble.destroy()
            except Exception:
                pass
            self.bubble = None
            self.bubble_canvas = None
            self.bubble_label = None

    def show_result_popup(self, text, char_count):
        self.hide_result_popup()

        self.result_popup = tk.Toplevel(self.root)
        self.result_popup.title("DECODED DATA")
        self.result_popup.config(bg=self.BG_COLOR)
        self.result_popup.attributes("-topmost", True)

        popup_w, popup_h = 540, 440
        screen_w = self.result_popup.winfo_screenwidth()
        screen_h = self.result_popup.winfo_screenheight()
        x = (screen_w - popup_w) // 2
        y = (screen_h - popup_h) // 2
        self.result_popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

        canvas = tk.Canvas(self.result_popup, bg=self.BG_COLOR, highlightthickness=0, bd=0,
                           width=popup_w, height=popup_h)
        canvas.pack(fill="both", expand=True)

        canvas.create_rectangle(3, 3, popup_w - 3, popup_h - 3, outline=self.BORDER_COLOR, width=5)
        canvas.create_rectangle(10, 10, popup_w - 10, popup_h - 10, outline=self.ACCENT_COLOR, width=2)

        header = tk.Label(canvas, text="DECODED DATA:", bg=self.BG_COLOR, fg=self.BORDER_COLOR,
                          font=(self.font_name, 12, "bold"))
        canvas.create_window(popup_w // 2, 32, window=header)

        sub = tk.Label(canvas, text=f"[ {char_count} characters ]", bg=self.BG_COLOR,
                       fg=self.ACCENT_COLOR, font=(self.font_name, 9))
        canvas.create_window(popup_w // 2, 58, window=sub)

        text_holder = tk.Frame(canvas, bg=self.BORDER_COLOR, bd=0, width=500, height=290)
        text_holder.pack_propagate(False)
        st = scrolledtext.ScrolledText(text_holder, wrap=tk.WORD,
                                       bg=self.ACCENT_COLOR, fg=self.BORDER_COLOR,
                                       font=(self.font_name, 10), relief="flat",
                                       insertbackground=self.BORDER_COLOR)
        st.pack(fill="both", expand=True, padx=3, pady=3)
        st.insert("1.0", text)
        st.config(state="disabled")
        canvas.create_window(popup_w // 2, 220, window=text_holder)

        footer = tk.Label(canvas, text=">> Copied to clipboard.", bg=self.BG_COLOR,
                          fg=self.BORDER_COLOR, font=(self.font_name, 9, "bold"))
        canvas.create_window(popup_w // 2, 400, window=footer)

        close_btn = tk.Button(canvas, text="[ X ]", bg=self.ACCENT_COLOR, fg=self.BORDER_COLOR,
                              font=(self.font_name, 9, "bold"), relief="flat",
                              command=self.hide_result_popup, cursor="hand2")
        canvas.create_window(popup_w - 40, 32, window=close_btn)

    def hide_result_popup(self):
        if self.result_popup:
            try:
                self.result_popup.destroy()
            except Exception:
                pass
            self.result_popup = None

    def hide_all(self):
        self.hide_bubble()
        self.hide_result_popup()


# =====================================================================
# DESKTOP PET — Original pet with OCR features integrated
# =====================================================================
class DesktopPet:
    def __init__(self, root, default_folder, wagging_folder, lift_folder, hi_folder, tongue_folder,
                 pat_pat_folder="pat-pat", walking_folder="WALKING", sleeping_folder="Sleeping", ocr_folder="OCR-ANIMATION"):
        self.root = root

        # --- WINDOW CONFIGURATION ---
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.transparent_color = '#000001'
        self.root.config(bg=self.transparent_color)
        self.root.attributes("-transparentcolor", self.transparent_color)

        # --- STATE INITIALIZATION ---
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.pil_frames = {}
        self.frames = {
            "default": self.load_frames(default_folder),
            "wagging": self.load_frames(wagging_folder),
            "lift": self.load_frames(lift_folder),
            "hi": self.load_frames(hi_folder),
            "tongue": self.load_frames(tongue_folder),
            "pat_pat": self.load_frames(pat_pat_folder),
            "walking_left": self.load_walking_sprite(walking_folder, "LEFT.png", "walking_left"),
            "walking_right": self.load_walking_sprite(walking_folder, "RIGHT.png", "walking_right"),
            "sleeping": self.load_frames(sleeping_folder, save_pil_key="sleeping"),
            "surprise": self.load_surprise_frames(os.path.join(self.base_dir, "RandomWebiste")),
            "ocr_animation": self.load_frames(ocr_folder) if os.path.isdir(ocr_folder) else []
        }
        self.current_state = "default"
        self.current_frame = 0
        self.x, self.y = 0, 0
        self.is_dragging = False
        self.action_count = 0
        self.sleep_timer = None
        self.context_menu = None
        self.zzz_windows = []
        self.zzz_timer = None
        self.surprise_active = False

        # --- OCR INTEGRATION ---
        self.ocr_engine = OCREngine()
        self.ocr_ui = RetroOcrUI(root)
        self.ocr_waiting = False
        self.ocr_processing = False

        # --- SMOOTH MOVEMENT & TIMING VARIABLES ---
        self.walk_speed = 5.5
        self.pos_x = float(self.root.winfo_x())
        self.pos_y = float(self.root.winfo_y())
        self.last_frame_time = time.time()

        # --- ANIMATION SPEEDS (Seconds per frame) ---
        self.normal_anim_speed = 0.1
        self.walk_anim_speed = 0.04

        # --- BOBBING EFFECT CONFIGURATION ---
        self.bob_amplitude = 8.0
        self.bob_frequency = 18.0

        self.label = tk.Label(root, bg=self.transparent_color, borderwidth=0, highlightthickness=0)
        self.label.pack()

        self.animate()
        self.root.after(6000, self.check_and_trigger_wagging)
        self.root.after(1000, self.check_and_trigger_tongue)

        self.label.bind("<ButtonPress-1>", self.start_move)
        self.label.bind("<B1-Motion>", self.do_move)
        self.label.bind("<ButtonRelease-1>", self.stop_move)
        self.label.bind("<Button-3>", self.show_context_menu)

        # --- OCR HOTKEY BINDINGS ---
        self.root.bind_all("<Control-v>", self.on_ctrl_v)
        self.root.bind_all("<Control-V>", self.on_ctrl_v)
        self.root.bind_all("<Control-Shift-v>", self.on_ctrl_shift_v)
        self.root.bind_all("<Control-Shift-V>", self.on_ctrl_shift_v)

    def load_frames(self, folder_path, flip=False, save_pil_key=None):
        frames = []
        pil_list = []
        files = sorted([f for f in os.listdir(folder_path) if f.endswith(".png")])
        for file in files:
            path = os.path.join(folder_path, file)
            img = Image.open(path).convert('RGBA').resize((150, 150), Image.Resampling.LANCZOS)
            if flip:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            alpha = img.split()[-1].point(lambda p: 255 if p > 128 else 0)
            img.putalpha(alpha)
            frames.append(ImageTk.PhotoImage(img))
            pil_list.append(img)
        if save_pil_key:
            self.pil_frames[save_pil_key] = pil_list
        return frames

    def load_walking_sprite(self, folder_path, filename, pil_key):
        frames = []
        pil_list = []
        path = os.path.join(folder_path, filename)
        if os.path.isfile(path):
            img = Image.open(path).convert("RGBA").resize((150, 150), Image.Resampling.LANCZOS)
            alpha = img.split()[-1].point(lambda p: 255 if p > 128 else 0)
            img.putalpha(alpha)
            frames.append(ImageTk.PhotoImage(img))
            pil_list.append(img)
        if pil_key:
            self.pil_frames[pil_key] = pil_list
        return frames

    def set_walk_sprite_for_direction(self, from_x, to_x):
        self.walk_sprite_key = "walking_left" if to_x < from_x else "walking_right"

    def load_surprise_frames(self, folder_path):
        frames = []
        if not os.path.isdir(folder_path):
            return frames
        files = sorted([
            f for f in os.listdir(folder_path)
            if os.path.splitext(f)[1].lower() in SURPRISE_IMAGE_EXTENSIONS
        ])
        for file in files:
            path = os.path.join(folder_path, file)
            img = Image.open(path).convert("RGBA").resize((150, 150), Image.Resampling.LANCZOS)
            alpha = img.split()[-1].point(lambda p: 255 if p > 128 else 0)
            img.putalpha(alpha)
            frames.append(ImageTk.PhotoImage(img))
        return frames

    def check_and_trigger_wagging(self):
        if self.current_state == "default" and not self.ocr_waiting and not self.ocr_processing:
            self.current_state = "wagging"
            self.current_frame = 0
            self.action_count = 0
        self.root.after(6000, self.check_and_trigger_wagging)

    def check_and_trigger_tongue(self):
        if self.current_state == "default" and not self.ocr_waiting and not self.ocr_processing:
            self.current_state = "tongue"
            self.current_frame = 0
            self.action_count = 0
        self.root.after(1000, self.check_and_trigger_tongue)

    def show_context_menu(self, event):
        self.close_context_menu()

        self.context_menu = tk.Toplevel(self.root)
        self.context_menu.overrideredirect(True)

        menu_trans_color = '#000002'
        self.context_menu.config(bg=menu_trans_color)
        self.context_menu.attributes("-transparentcolor", menu_trans_color)
        self.context_menu.attributes("-topmost", True)
        self.context_menu.geometry(f"+{event.x_root}+{event.y_root}")

        item_height = 35
        width = 130
        menu_items = [("Sleep", self.on_sleep_click)]
        if not self.is_asleep():
            menu_items.append(("Surprise me!", self.on_surprise_click))
            menu_items.append(("OCR", self.on_ocr_click))
        height = item_height * len(menu_items)
        radius = 12

        canvas = tk.Canvas(self.context_menu, width=width, height=height, bg=menu_trans_color, highlightthickness=0)
        canvas.pack()

        bg_color = "#D2B48C"
        canvas.create_oval(0, 0, radius*2, radius*2, fill=bg_color, outline="")
        canvas.create_oval(width-radius*2, 0, width, radius*2, fill=bg_color, outline="")
        canvas.create_oval(0, height-radius*2, radius*2, height, fill=bg_color, outline="")
        canvas.create_oval(width-radius*2, height-radius*2, width, height, fill=bg_color, outline="")
        canvas.create_rectangle(radius, 0, width-radius, height, fill=bg_color, outline="")
        canvas.create_rectangle(0, radius, width, height-radius, fill=bg_color, outline="")

        for index, (label_text, command) in enumerate(menu_items):
            item = tk.Label(canvas, text=label_text, bg=bg_color, fg="#4A2F13", font=("Arial", 10), cursor="hand2")
            canvas.create_window(width // 2, item_height // 2 + index * item_height, window=item)
            item.bind("<Enter>", lambda e, lbl=item: lbl.config(bg="#8B5A2B", fg="white"))
            item.bind("<Leave>", lambda e, lbl=item: lbl.config(bg=bg_color, fg="#4A2F13"))
            item.bind("<Button-1>", lambda e, cmd=command: cmd())

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

    def is_asleep(self):
        return self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]

    def on_sleep_click(self):
        self.close_context_menu()
        if self.current_state in ["walking_down", "sleeping_phase1", "sleeping_phase2", "sleeping_phase3", "walking_up"]:
            return
        if self.ocr_waiting or self.ocr_processing:
            return
        self.start_sleep_flow()

    def on_surprise_click(self):
        self.close_context_menu()
        if self.is_asleep() or self.surprise_active:
            return
        if self.ocr_waiting or self.ocr_processing:
            return
        self.start_surprise_flow()

    def load_random_website_url(self):
        websites_file = os.path.join(self.base_dir, "Random Websites.txt")
        with open(websites_file, "r", encoding="utf-8") as file:
            urls = [line.strip() for line in file if line.strip()]
        if not urls:
            raise ValueError("No websites found in Random Websites.txt")
        return random.choice(urls)

    def start_surprise_flow(self):
        surprise_frames = self.frames.get("surprise", [])
        if not surprise_frames:
            self.finish_surprise_flow()
            return
        self.surprise_active = True
        self.current_state = "surprise"
        self.current_frame = 0
        self.action_count = 0

    def finish_surprise_flow(self):
        try:
            webbrowser.open(self.load_random_website_url())
        except Exception:
            pass
        finally:
            self.surprise_active = False

    def start_sleep_flow(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        current_x = self.root.winfo_x()

        if current_x >= screen_width / 2:
            self.walk_target_x = 0
        else:
            self.walk_target_x = screen_width - 150

        self.walk_target_y = screen_height - 150
        self.set_walk_sprite_for_direction(current_x, self.walk_target_x)

        self.pos_x = float(current_x)
        self.pos_y = float(self.root.winfo_y())

        self.current_state = "walking_down"
        self.current_frame = 0

    def fade_transition(self, start_pil, end_pil, duration_ms, callback):
        steps = 15
        interval = duration_ms // steps

        def step(count):
            if self.current_state not in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
                return
            if count > steps:
                callback()
                return

            alpha = count / steps
            blended = Image.blend(start_pil, end_pil, alpha)

            r, g, b, a = blended.split()
            binary_a = a.point(lambda p: 255 if p > 128 else 0)
            blended.putalpha(binary_a)

            self.fade_photo = ImageTk.PhotoImage(blended)
            self.label.config(image=self.fade_photo)
            self.root.after(interval, lambda: step(count + 1))

        step(0)

    def enter_sleep_state(self):
        if self.sleep_timer:
            self.root.after_cancel(self.sleep_timer)
        self.current_state = "sleeping_phase1"
        self.current_frame = 0

        walk_key = getattr(self, "walk_sprite_key", "walking_right")
        w_idx = min(self.current_frame, len(self.pil_frames[walk_key]) - 1)
        start_img = self.pil_frames[walk_key][w_idx]
        end_img = self.pil_frames["sleeping"][0]

        self.fade_transition(start_img, end_img, 800,
                            lambda: setattr(self, "sleep_timer", self.root.after(2200, self.enter_sleep_phase2)))

    def enter_sleep_phase2(self):
        self.current_state = "sleeping_phase2"
        self.current_frame = 1

        start_img = self.pil_frames["sleeping"][0]
        end_img = self.pil_frames["sleeping"][1]

        self.fade_transition(start_img, end_img, 800,
                            lambda: setattr(self, "sleep_timer", self.root.after(4200, self.enter_sleep_phase3)))

    def enter_sleep_phase3(self):
        self.current_state = "sleeping_phase3"
        self.current_frame = 2
        self.sleep_timer = None

        start_img = self.pil_frames["sleeping"][1]
        end_img = self.pil_frames["sleeping"][2]

        self.fade_transition(start_img, end_img, 800, self.start_zzz_loop)

    def start_zzz_loop(self):
        if self.current_state != "sleeping_phase3":
            return
        self.zzz_windows = []
        self.spawn_zzz()

    def spawn_zzz(self):
        if self.current_state != "sleeping_phase3":
            return

        z_win = tk.Toplevel(self.root)
        z_win.overrideredirect(True)
        z_bg = '#000001'
        z_win.config(bg=z_bg)
        z_win.attributes("-transparentcolor", z_bg)
        z_win.attributes("-topmost", True)

        z_char = random.choice(["z", "Z", "zZ"])
        z_color = random.choice(["#9370DB", "#8A2BE2", "#4B0082", "#A0522D", "#5C4033"])
        font_size = random.randint(10, 16)

        lbl = tk.Label(z_win, text=z_char, bg=z_bg, fg=z_color, font=("Comic Sans MS", font_size, "bold"))
        lbl.pack()

        rx = self.root.winfo_x() + 45 + random.randint(-15, 15)
        ry = self.root.winfo_y() + 25 + random.randint(-10, 10)
        z_win.geometry(f"+{rx}+{ry}")

        self.zzz_windows.append(z_win)

        def drift(win, x, y, age=0):
            if self.current_state != "sleeping_phase3" or win not in self.zzz_windows:
                try:
                    win.destroy()
                except Exception:
                    pass
                if win in self.zzz_windows:
                    self.zzz_windows.remove(win)
                return

            if age > 40:
                try:
                    win.destroy()
                except Exception:
                    pass
                if win in self.zzz_windows:
                    self.zzz_windows.remove(win)
                return

            new_y = y - 3
            new_x = x + int(random.choice([-2, -1, 0, 1, 2]))
            try:
                win.geometry(f"+{new_x}+{new_y}")
            except Exception:
                return

            self.root.after(50, lambda: drift(win, new_x, new_y, age + 1))

        drift(z_win, rx, ry)
        self.zzz_timer = self.root.after(1200, self.spawn_zzz)

    def cleanup_zzz(self):
        if hasattr(self, "zzz_timer") and self.zzz_timer:
            try:
                self.root.after_cancel(self.zzz_timer)
            except Exception:
                pass
            self.zzz_timer = None

        if hasattr(self, "zzz_windows"):
            for win in self.zzz_windows:
                try:
                    win.destroy()
                except Exception:
                    pass
            self.zzz_windows = []

    def wake_up(self):
        self.cleanup_zzz()
        if self.sleep_timer:
            self.root.after_cancel(self.sleep_timer)
            self.sleep_timer = None

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        min_x = int(screen_width * 0.6)
        max_x = max(min_x + 1, int(screen_width * 0.9) - 150)
        self.walk_target_x = random.randint(min_x, max_x)

        min_y = 10
        max_y = max(min_y + 1, int(screen_height * 0.6) - 150)
        self.walk_target_y = random.randint(min_y, max_y)

        current_x = self.root.winfo_x()
        self.set_walk_sprite_for_direction(current_x, self.walk_target_x)

        self.pos_x = float(current_x)
        self.pos_y = float(self.root.winfo_y())

        self.current_state = "walking_up"
        self.current_frame = 0

    # =================================================================
    # OCR FLOW METHODS
    # =================================================================
    def on_ocr_click(self):
        self.close_context_menu()
        if self.is_asleep() or self.surprise_active or self.ocr_processing or self.ocr_waiting:
            return
        if not self.ocr_engine.available:
            self.ocr_ui.show_bubble("OCR not available!", 2500)
            return
        self.ocr_waiting = True
        self.ocr_ui.show_bubble("Paste the image!")

    def on_ctrl_v(self, event):
        if not self.ocr_waiting:
            return 
        if self.is_asleep() or self.surprise_active or self.ocr_processing:
            self.ocr_waiting = False
            return "break"
        if not self.ocr_engine.available:
            self.ocr_waiting = False
            self.ocr_ui.show_bubble("OCR not available!", 2500)
            return "break"
        self.start_ocr_processing()
        return "break"

    def on_ctrl_shift_v(self, event):
        if self.is_asleep() or self.surprise_active or self.ocr_processing or self.ocr_waiting:
            return "break"
        if not self.ocr_engine.available:
            self.ocr_ui.show_bubble("OCR not available!", 2500)
            return "break"
        self.start_ocr_processing()
        return "break"

    def start_ocr_processing(self):
        self.ocr_waiting = False
        self.ocr_processing = True
        
        # Switch to OCR-ANIMATION state, play frames, and pause on last frame
        # If folder is missing/empty, stay in default but block all clicks
        if self.frames.get("ocr_animation") and len(self.frames["ocr_animation"]) > 0:
            self.current_state = "ocr_animation"
            self.current_frame = 0

        self.ocr_ui.show_bubble("Scanning...")
        # Process image entirely in background thread
        self.ocr_engine.process_image(self.on_ocr_complete)

    def on_ocr_complete(self, text, error):
        self.root.after(0, lambda: self._handle_ocr_result(text, error))

    def _handle_ocr_result(self, text, error):
        if error:
            self.ocr_ui.show_bubble(error, 3500)
            self.root.after(3700, self._reset_ocr_state)
            return

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception:
            pass

        if len(text) > 100:
            self.ocr_ui.show_bubble(f"Found {len(text)} characters!")
            self.root.after(1500, lambda: self.ocr_ui.show_result_popup(text, len(text)))
            self.root.after(5000, self._reset_ocr_state)  # Give time to view the popup
        else:
            self.ocr_ui.show_bubble(text, 2000)
            # Wait 2s, then show "Mission complete!" for exactly 3.5s (3500ms)
            self.root.after(2000, lambda: self.ocr_ui.show_bubble("Mission complete!", 3500))
            self.root.after(5500, self._reset_ocr_state)  # 2000 + 3500 = 5500ms total

    def _reset_ocr_state(self):
        self.ocr_waiting = False
        self.ocr_processing = False
        self.ocr_ui.hide_bubble()
        self.current_state = "default"
        self.current_frame = 0
        self.action_count = 0

    def animate(self):
        frame_key = self.current_state
        if self.current_state in ["walking_down", "walking_up"]:
            frame_key = getattr(self, "walk_sprite_key", "walking_right")
        elif self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            frame_key = "sleeping"

        state_frames = self.frames.get(frame_key)

        if state_frames:
            if self.current_state == "sleeping_phase1":
                self.current_frame = 0
            elif self.current_state == "sleeping_phase2":
                self.current_frame = 1
            elif self.current_state == "sleeping_phase3":
                self.current_frame = 2

            if self.current_state not in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
                self.label.config(image=state_frames[self.current_frame])

            if self.current_state in ["walking_down", "walking_up"]:
                current_delay = self.walk_anim_speed
            elif self.current_state == "surprise":
                current_delay = SURPRISE_ANIM_SPEED
            else:
                current_delay = self.normal_anim_speed

            current_time = time.time()
            if current_time - self.last_frame_time >= current_delay:
                self.last_frame_time = current_time

                # Handle OCR Animation (Play once and freeze on last frame)
                if self.current_state == "ocr_animation":
                    if self.current_frame < len(state_frames) - 1:
                        self.current_frame += 1
                        
                elif self.current_state in ["wagging", "hi", "tongue", "pat_pat", "surprise"]:
                    if self.current_frame < len(state_frames) - 1:
                        self.current_frame += 1
                    else:
                        self.current_frame = 0
                        self.action_count += 1

                        if self.current_state == "wagging": limit = 5
                        elif self.current_state == "hi": limit = 6
                        elif self.current_state == "pat_pat": limit = 5
                        else: limit = 1

                        if self.action_count >= limit:
                            if self.current_state == "surprise":
                                self.finish_surprise_flow()
                            self.current_state = "default"
                            self.action_count = 0
                elif self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
                    pass
                else:
                    self.current_frame = (self.current_frame + 1) % len(state_frames)

            if self.current_state == "walking_down":
                dx = self.walk_target_x - self.pos_x
                dy = self.walk_target_y - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5

                if dist > self.walk_speed:
                    self.pos_x += (dx / dist) * self.walk_speed
                    self.pos_y += (dy / dist) * self.walk_speed
                    bob_offset = math.sin(time.time() * self.bob_frequency) * self.bob_amplitude
                    self.root.geometry(f"+{round(self.pos_x)}+{round(self.pos_y + bob_offset)}")
                else:
                    self.root.geometry(f"+{self.walk_target_x}+{self.walk_target_y}")
                    self.pos_x, self.pos_y = float(self.walk_target_x), float(self.walk_target_y)
                    self.enter_sleep_state()

            elif self.current_state == "walking_up":
                dx = self.walk_target_x - self.pos_x
                dy = self.walk_target_y - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5

                if dist > self.walk_speed:
                    self.pos_x += (dx / dist) * self.walk_speed
                    self.pos_y += (dy / dist) * self.walk_speed
                    bob_offset = math.sin(time.time() * self.bob_frequency) * self.bob_amplitude
                    self.root.geometry(f"+{round(self.pos_x)}+{round(self.pos_y + bob_offset)}")
                else:
                    self.root.geometry(f"+{self.walk_target_x}+{self.walk_target_y}")
                    self.pos_x, self.pos_y = float(self.walk_target_x), float(self.walk_target_y)
                    self.current_state = "default"
                    self.current_frame = 0

        self.ocr_ui.update_pet_pos(self.root.winfo_x(), self.root.winfo_y())
        self.root.after(16, self.animate)

    def start_move(self, event):
        # Ignore left clicks completely while OCR is active
        if self.ocr_processing or self.ocr_waiting:
            return

        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            self.x = event.x
            self.y = event.y
            self.is_dragging = False
            return
        if self.current_state in ["walking_down", "walking_up", "surprise", "ocr_animation"]:
            return
        self.x, self.y = event.x, event.y
        self.is_dragging = False

    def do_move(self, event):
        # Ignore left clicks completely while OCR is active
        if self.ocr_processing or self.ocr_waiting:
            return

        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            self.is_dragging = True
            x = self.root.winfo_x() + (event.x - self.x)
            y = self.root.winfo_y()
            self.root.geometry(f"+{x}+{y}")
            self.pos_x = float(x)
            self.pos_y = float(y)
            return

        if self.current_state in ["walking_down", "walking_up", "surprise", "ocr_animation"]:
            return

        if not self.is_dragging:
            self.is_dragging = True
            self.current_state = "lift"
            self.current_frame = 0

        x = self.root.winfo_x() + (event.x - self.x)
        y = self.root.winfo_y() + (event.y - self.y)
        self.root.geometry(f"+{x}+{y}")
        self.pos_x = float(x)
        self.pos_y = float(y)

    def stop_move(self, event):
        # Ignore left clicks completely while OCR is active
        if self.ocr_processing or self.ocr_waiting:
            return

        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            if self.current_state == "sleeping_phase3" and not self.is_dragging:
                self.wake_up()
            self.is_dragging = False
            return
        if self.current_state in ["walking_down", "walking_up", "surprise", "ocr_animation"]:
            return
        if not self.is_dragging and self.current_state == "default":
            if random.choice([True, False]):
                self.current_state = "pat_pat"
            else:
                self.current_state = "hi"
            self.current_frame = 0
            self.action_count = 0
        else:
            self.current_state = "default"
            self.current_frame = 0

        self.is_dragging = False


if __name__ == "__main__":
    root = tk.Tk()
    pet_app = DesktopPet(root, "default", "wagging", "lift", "hi", "TONGUE")
    root.mainloop()