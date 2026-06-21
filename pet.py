import tkinter as tk
from tkinter import scrolledtext, simpledialog, messagebox
from PIL import Image, ImageTk, ImageGrab
import os
import random
import time
import math
import webbrowser
import threading
import warnings
import tkinter.font as tkfont
import json
import requests
import re
import html
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# =====================================================================
# CONFIGURATION & VARIABLES
# =====================================================================
SYNC_COUNT = 20             # Number of latest submissions to fetch
INITIAL_REVIEW_DAYS = 10    # Days before 1st review
POSTPONE_HOURS = 2          # Hours to postpone if "Later" or "Let's Try" is clicked
NEXT_REVIEW_DAYS = 30       # Days to schedule after "Completed" is clicked
AUTO_SYNC_INTERVAL_MIN = 30 # Minutes between automatic background syncs

SURPRISE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
SURPRISE_ANIM_SPEED = 0.5

# ---- PaddleOCR availability check ----
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
# LEETCODE SCRAPER MODULE
# =====================================================================
class LeetCodeScraper:
    def __init__(self, data_file):
        self.data_file = data_file
        self.data = {
            "profile": "",
            "tracked": [],
            "ask_queue": [],
            "completed": []
        }
        self.load_data()

    def load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def save_data(self):
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Error saving LeetCode data: {e}")

    def set_profile(self, username):
        self.data["profile"] = username
        self.save_data()

    def get_profile(self):
        return self.data.get("profile", "")

    def get_pending_count(self):
        # ONLY count questions in the active ask_queue
        return len(self.data["ask_queue"])

    def clear_all_revisions(self):
        self.data["tracked"] = []
        self.data["ask_queue"] = []
        self.data["completed"] = []
        self.save_data()

    def _fetch_submissions(self, username):
        url = "https://leetcode.com/graphql/"
        headers = {"Content-Type": "application/json"}
        query = """
        query recentSubmissionList($username: String!, $limit: Int!) {
            recentSubmissionList(username: $username, limit: $limit) {
                title
                titleSlug
                timestamp
            }
        }
        """
        payload = {
            "query": query,
            "variables": {"username": username, "limit": SYNC_COUNT}
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("recentSubmissionList", [])
        except Exception as e:
            print(f"LeetCode API Error (Submissions): {e}")
        return []

    def _fetch_question_details(self, title_slug):
        url = "https://leetcode.com/graphql/"
        headers = {"Content-Type": "application/json"}
        query = """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                title
                content
                sampleTestCase
            }
        }
        """
        payload = {
            "query": query,
            "variables": {"titleSlug": title_slug}
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                q_data = resp.json().get("data", {}).get("question", {})
                if q_data:
                    raw_html = q_data.get("content", "")
                    clean_text = re.sub(r'<[^>]+>', '', raw_html)
                    clean_text = html.unescape(clean_text)
                    
                    sample = q_data.get("sampleTestCase", "")
                    parts = sample.split("\n")
                    example_input = parts[0] if parts else ""
                    example_output = parts[1] if len(parts) > 1 else ""
                    
                    return {
                        "description": clean_text.strip(),
                        "example_input": example_input,
                        "example_output": example_output
                    }
        except Exception as e:
            print(f"LeetCode API Error (Details): {e}")
        return None

    def sync(self, callback=None):
        def worker():
            username = self.get_profile()
            if not username:
                if callback: callback(False, "No profile set")
                return

            subs = self._fetch_submissions(username)
            if not subs:
                if callback: callback(False, "Failed to fetch or no submissions")
                return

            recent_subs_dict = {sub.get("titleSlug"): sub.get("timestamp") for sub in subs}

            # 1. Auto-complete questions from ask_queue if solved AGAIN
            auto_completed = []
            still_ask_queue = []
            for q in self.data["ask_queue"]:
                ts = recent_subs_dict.get(q["titleSlug"])
                if ts:
                    try:
                        sub_time = datetime.fromtimestamp(int(ts))
                        ask_time = datetime.fromisoformat(q["ask_date"])
                        # CRITICAL FIX: Only auto-complete if submitted AFTER it entered the queue
                        if sub_time > ask_time:
                            self.data["completed"].append({
                                "titleSlug": q["titleSlug"],
                                "title": q["title"],
                                "next_ask_date": (datetime.now() + timedelta(days=NEXT_REVIEW_DAYS)).isoformat(),
                                "review_stage": q.get("review_stage", 1) + 1
                            })
                            auto_completed.append(q)
                            continue
                    except:
                        pass
                still_ask_queue.append(q)
            self.data["ask_queue"] = still_ask_queue

            # 2. Add brand new problems to tracked
            known_slugs = set()
            for item in self.data["tracked"]: known_slugs.add(item["titleSlug"])
            for item in self.data["ask_queue"]: known_slugs.add(item["titleSlug"])
            for item in self.data["completed"]: known_slugs.add(item["titleSlug"])

            new_count = 0
            now = datetime.now()
            for sub in subs:
                slug = sub.get("titleSlug")
                if slug and slug not in known_slugs:
                    ts = sub.get("timestamp")
                    try:
                        date_solved = datetime.fromtimestamp(int(ts)).isoformat()
                    except Exception:
                        date_solved = now.isoformat()

                    ask_date = (datetime.fromisoformat(date_solved) + timedelta(days=INITIAL_REVIEW_DAYS)).isoformat()
                    
                    self.data["tracked"].append({
                        "titleSlug": slug,
                        "title": sub.get("title", slug),
                        "date_solved": date_solved,
                        "ask_date": ask_date
                    })
                    known_slugs.add(slug)
                    new_count += 1

            self.save_data()
            msg = f"Synced! {new_count} new problems tracked."
            if auto_completed:
                msg += f" {len(auto_completed)} problem(s) auto-completed!"
            if callback: callback(True, msg)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def process_queue(self, callback=None):
        """Checks maturity and returns the next eligible question to ask."""
        def worker():
            now = datetime.now()
            
            # 1. Move matured items from tracked/completed to ask_queue
            promoted = []
            still_tracked = []
            still_completed = []

            for item in self.data["tracked"]:
                ask_dt = datetime.fromisoformat(item["ask_date"])
                if ask_dt <= now:
                    details = self._fetch_question_details(item["titleSlug"])
                    if details:
                        q_item = {
                            "titleSlug": item["titleSlug"],
                            "title": item["title"],
                            "description": details["description"],
                            "example_input": details["example_input"],
                            "example_output": details["example_output"],
                            "url": f"https://leetcode.com/problems/{item['titleSlug']}/",
                            "ask_date": item["ask_date"],
                            "review_stage": 1
                        }
                        promoted.append(q_item)
                    else:
                        item["ask_date"] = (now + timedelta(days=1)).isoformat()
                        still_tracked.append(item)
                else:
                    still_tracked.append(item)

            for item in self.data["completed"]:
                ask_dt = datetime.fromisoformat(item["next_ask_date"])
                if ask_dt <= now:
                    details = self._fetch_question_details(item["titleSlug"])
                    if details:
                        q_item = {
                            "titleSlug": item["titleSlug"],
                            "title": item["title"],
                            "description": details["description"],
                            "example_input": details["example_input"],
                            "example_output": details["example_output"],
                            "url": f"https://leetcode.com/problems/{item['titleSlug']}/",
                            "ask_date": item["next_ask_date"],
                            "review_stage": item.get("review_stage", 2)
                        }
                        promoted.append(q_item)
                    else:
                        item["next_ask_date"] = (now + timedelta(days=1)).isoformat()
                        still_completed.append(item)
                else:
                    still_completed.append(item)

            if promoted:
                self.data["tracked"] = still_tracked
                self.data["completed"] = still_completed
                self.data["ask_queue"].extend(promoted)
                self.save_data()

            # 2. Check ask_queue for items ready to be shown (ask_date <= now)
            question_to_ask = None
            for q in self.data["ask_queue"]:
                if datetime.fromisoformat(q["ask_date"]) <= now:
                    question_to_ask = q
                    break
            
            if callback: callback(question_to_ask is not None, question_to_ask)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def force_ask(self, callback=None):
        """Bypasses the ask_date timer ONLY for questions already in the ask_queue."""
        def worker():
            if self.data["ask_queue"]:
                # Return the first question in the queue, skipping any snooze timer
                if callback: callback(True, self.data["ask_queue"][0])
            else:
                if callback: callback(False, None)
                
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def action_later(self, question):
        """Postpone the question by 2 hours."""
        if question in self.data["ask_queue"]:
            question["ask_date"] = (datetime.now() + timedelta(hours=POSTPONE_HOURS)).isoformat()
            self.data["ask_queue"].remove(question)
            self.data["ask_queue"].append(question)
            self.save_data()

    def action_try(self, question):
        """Postpone the question so it doesn't pop up immediately, but keep it in the queue."""
        if question in self.data["ask_queue"]:
            question["ask_date"] = (datetime.now() + timedelta(hours=POSTPONE_HOURS)).isoformat()
            self.data["ask_queue"].remove(question)
            self.data["ask_queue"].append(question)
            self.save_data()

    def action_complete(self, question):
        if question in self.data["ask_queue"]:
            self.data["ask_queue"].remove(question)
            self.data["completed"].append({
                "titleSlug": question["titleSlug"],
                "title": question["title"],
                "next_ask_date": (datetime.now() + timedelta(days=NEXT_REVIEW_DAYS)).isoformat(),
                "review_stage": question.get("review_stage", 1) + 1
            })
            self.save_data()


# =====================================================================
# OCR ENGINE
# =====================================================================
class OCREngine:
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
        except Exception:
            try:
                self.ocr = PaddleOCR(
                    lang='en', 
                    enable_mkldnn=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False
                )
            except Exception:
                self.ocr = None
                self.available = False

    def get_clipboard_image(self):
        try:
            grabbed = ImageGrab.grabclipboard()
            if grabbed is None: return None
            if isinstance(grabbed, Image.Image): return grabbed
            if isinstance(grabbed, list) and len(grabbed) > 0:
                path = grabbed[0]
                if isinstance(path, str):
                    ext = os.path.splitext(path)[1].lower()
                    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"):
                        return Image.open(path)
            return None
        except Exception:
            return None

    def _extract_text(self, pil_image):
        import tempfile
        tmp_path = None
        try:
            if self.ocr is None: return ""
            if pil_image.mode != 'RGB': pil_image = pil_image.convert('RGB')
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp: tmp_path = tmp.name
            pil_image.save(tmp_path, format="PNG")
            raw = self.ocr.ocr(tmp_path)
            collected = []
            if raw is None: return ""
            if isinstance(raw, dict): raw = [raw]
            if not isinstance(raw, (list, tuple)): return ""
            for page in raw:
                if isinstance(page, dict):
                    texts = page.get("rec_texts", [])
                    if isinstance(texts, str): texts = [texts]
                    for txt in texts:
                        if isinstance(txt, str):
                            if '<' in txt and '>' in txt and '::' in txt: continue
                            if txt.strip(): collected.append(txt)
                elif isinstance(page, (list, tuple)):
                    for item in page:
                        if not isinstance(item, (list, tuple)) or len(item) < 2: continue
                        text_info = item[1]
                        if isinstance(text_info, (list, tuple)) and len(text_info) >= 1: txt = text_info[0]
                        elif isinstance(text_info, str): txt = text_info
                        else: continue
                        if not isinstance(txt, str): continue
                        if '<' in txt and '>' in txt and '::' in txt: continue
                        if txt.strip(): collected.append(txt)
            return " ".join(collected)
        except Exception:
            return ""
        finally:
            if tmp_path:
                try: os.remove(tmp_path)
                except: pass

    def process_image(self, callback):
        def worker():
            text = ""
            error = None
            img = self.get_clipboard_image()
            if img is None:
                callback("", "No image detected!")
                return
            try:
                text = self._extract_text(img)
                if not text: error = "No readable text found."
            except Exception:
                error = "OCR Error"
            callback(text, error)
        threading.Thread(target=worker, daemon=True).start()


# =====================================================================
# RETRO OCR UI
# =====================================================================
class RetroOcrUI:
    BG_COLOR = "#FFF8DC"
    BORDER_COLOR = "#4A2F13"
    ACCENT_COLOR = "#D2B48C"

    def __init__(self, root):
        self.root = root
        self.bubble = None
        self.result_popup = None
        self.pet_x = 0
        self.pet_y = 0
        self._bubble_after = None
        self.font_name = self._pick_font()

    def _pick_font(self):
        try: available = tkfont.families()
        except: available = []
        for c in ["Press Start 2P", "VT323", "Pixelated", "Courier New"]:
            if c in available: return c
        return "Courier New"

    def update_pet_pos(self, x, y):
        self.pet_x = x
        self.pet_y = y
        if self.bubble: self._position_bubble()

    def show_bubble(self, text, duration=None):
        self.hide_bubble()
        self.bubble = tk.Toplevel(self.root)
        self.bubble.overrideredirect(True)
        self.bubble.config(bg=self.BG_COLOR)
        self.bubble.attributes("-topmost", True)
        measure = tk.Label(self.bubble, text=text, bg=self.BG_COLOR, fg=self.BORDER_COLOR, font=(self.font_name, 10, "bold"), padx=14, pady=8)
        measure.update_idletasks()
        lw, lh = measure.winfo_reqwidth(), measure.winfo_reqheight()
        measure.destroy()
        bw, pad = 3, 4
        tw, th = lw + pad*2, lh + pad*2
        c = tk.Canvas(self.bubble, width=tw, height=th, bg=self.BG_COLOR, highlightthickness=0, bd=0)
        c.pack()
        c.create_rectangle(bw//2, bw//2, tw-bw//2, th-bw//2, outline=self.BORDER_COLOR, width=bw)
        lbl = tk.Label(c, text=text, bg=self.BG_COLOR, fg=self.BORDER_COLOR, font=(self.font_name, 10, "bold"))
        c.create_window(tw//2, th//2, window=lbl)
        self._position_bubble()
        if duration:
            if self._bubble_after:
                try: self.root.after_cancel(self._bubble_after)
                except: pass
            self._bubble_after = self.root.after(duration, self.hide_bubble)

    def _position_bubble(self):
        if not self.bubble: return
        self.bubble.update_idletasks()
        w, h = self.bubble.winfo_reqwidth(), self.bubble.winfo_reqheight()
        x, y = self.pet_x + 75 - w//2, self.pet_y - h - 8
        if y < 0: y = self.pet_y + 150 + 8
        if x < 0: x = 0
        sw = self.root.winfo_screenwidth()
        if x + w > sw: x = sw - w
        try: self.bubble.geometry(f"+{x}+{y}")
        except: pass

    def hide_bubble(self):
        if self._bubble_after:
            try: self.root.after_cancel(self._bubble_after)
            except: pass
            self._bubble_after = None
        if self.bubble:
            try: self.bubble.destroy()
            except: pass
            self.bubble = None

    def show_result_popup(self, text, char_count):
        self.hide_result_popup()
        self.result_popup = tk.Toplevel(self.root)
        self.result_popup.title("DECODED DATA")
        self.result_popup.config(bg=self.BG_COLOR)
        self.result_popup.attributes("-topmost", True)
        pw, ph = 540, 440
        sw, sh = self.result_popup.winfo_screenwidth(), self.result_popup.winfo_screenheight()
        self.result_popup.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")
        c = tk.Canvas(self.result_popup, bg=self.BG_COLOR, highlightthickness=0, bd=0, width=pw, height=ph)
        c.pack(fill="both", expand=True)
        c.create_rectangle(3, 3, pw-3, ph-3, outline=self.BORDER_COLOR, width=5)
        c.create_rectangle(10, 10, pw-10, ph-10, outline=self.ACCENT_COLOR, width=2)
        c.create_window(pw//2, 32, window=tk.Label(c, text="DECODED DATA:", bg=self.BG_COLOR, fg=self.BORDER_COLOR, font=(self.font_name, 12, "bold")))
        c.create_window(pw//2, 58, window=tk.Label(c, text=f"[ {char_count} characters ]", bg=self.BG_COLOR, fg=self.ACCENT_COLOR, font=(self.font_name, 9)))
        th = tk.Frame(c, bg=self.BORDER_COLOR, bd=0, width=500, height=290)
        th.pack_propagate(False)
        st = scrolledtext.ScrolledText(th, wrap=tk.WORD, bg=self.ACCENT_COLOR, fg=self.BORDER_COLOR, font=(self.font_name, 10), relief="flat")
        st.pack(fill="both", expand=True, padx=3, pady=3)
        st.insert("1.0", text)
        st.config(state="disabled")
        c.create_window(pw//2, 220, window=th)
        c.create_window(pw//2, 400, window=tk.Label(c, text=">> Copied to clipboard.", bg=self.BG_COLOR, fg=self.BORDER_COLOR, font=(self.font_name, 9, "bold")))
        c.create_window(pw-40, 32, window=tk.Button(c, text="[ X ]", bg=self.ACCENT_COLOR, fg=self.BORDER_COLOR, font=(self.font_name, 9, "bold"), relief="flat", command=self.hide_result_popup))

    def hide_result_popup(self):
        if self.result_popup:
            try: self.result_popup.destroy()
            except: pass
            self.result_popup = None

    def hide_all(self):
        self.hide_bubble()
        self.hide_result_popup()


# =====================================================================
# DESKTOP PET
# =====================================================================
class DesktopPet:
    def __init__(self, root, default_folder, wagging_folder, lift_folder, hi_folder, tongue_folder,
                 pat_pat_folder="pat-pat", walking_folder="WALKING", sleeping_folder="Sleeping", ocr_folder="OCR-ANIMATION",
                 dsa_folder="DSA"):
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
        
        def safe_load(path):
            return self.load_frames(path) if os.path.isdir(path) else []
            
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
            "ocr_animation": safe_load(ocr_folder),
            "dsa_randomwebsite": safe_load(os.path.join(dsa_folder, "Randomwebsite")),
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

        # --- LEETCODE INTEGRATION ---
        self.leetcode_scraper = LeetCodeScraper(os.path.join(self.base_dir, "leetcode_data.json"))
        self.leetcode_question_active = False
        self.leetcode_try_url = None
        self.leetcode_popup = None
        self.leetcode_preview_win = None

        # --- SMOOTH MOVEMENT & TIMING VARIABLES ---
        self.walk_speed = 5.5
        self.pos_x = float(self.root.winfo_x())
        self.pos_y = float(self.root.winfo_y())
        self.last_frame_time = time.time()

        # --- ANIMATION SPEEDS ---
        self.normal_anim_speed = 0.1
        self.walk_anim_speed = 0.04

        # --- BOBBING EFFECT ---
        self.bob_amplitude = 8.0
        self.bob_frequency = 18.0

        self.label = tk.Label(root, bg=self.transparent_color, borderwidth=0, highlightthickness=0)
        self.label.pack()

        self.animate()
        self.root.after(6000, self.check_and_trigger_wagging)
        self.root.after(1000, self.check_and_trigger_tongue)
        self.root.after(60000, self.check_leetcode_queue) # Check queue every 60s
        self.root.after(10000, self.auto_sync_leetcode)   # Auto-sync 10s after startup

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
        if not os.path.isdir(folder_path): return frames
        files = sorted([f for f in os.listdir(folder_path) if f.endswith(".png")])
        for file in files:
            path = os.path.join(folder_path, file)
            try:
                img = Image.open(path).convert('RGBA').resize((150, 150), Image.Resampling.LANCZOS)
                if flip: img = img.transpose(Image.FLIP_LEFT_RIGHT)
                alpha = img.split()[-1].point(lambda p: 255 if p > 128 else 0)
                img.putalpha(alpha)
                frames.append(ImageTk.PhotoImage(img))
                pil_list.append(img)
            except Exception as e:
                print(f"Error loading {path}: {e}")
        if save_pil_key: self.pil_frames[save_pil_key] = pil_list
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
        if pil_key: self.pil_frames[pil_key] = pil_list
        return frames

    def set_walk_sprite_for_direction(self, from_x, to_x):
        self.walk_sprite_key = "walking_left" if to_x < from_x else "walking_right"

    def load_surprise_frames(self, folder_path):
        frames = []
        if not os.path.isdir(folder_path): return frames
        files = sorted([f for f in os.listdir(folder_path) if os.path.splitext(f)[1].lower() in SURPRISE_IMAGE_EXTENSIONS])
        for file in files:
            path = os.path.join(folder_path, file)
            img = Image.open(path).convert("RGBA").resize((150, 150), Image.Resampling.LANCZOS)
            alpha = img.split()[-1].point(lambda p: 255 if p > 128 else 0)
            img.putalpha(alpha)
            frames.append(ImageTk.PhotoImage(img))
        return frames

    def check_and_trigger_wagging(self):
        # Allow idle animations even if LeetCode question is active
        if self.current_state == "default" and not self.ocr_waiting and not self.ocr_processing:
            self.current_state = "wagging"
            self.current_frame = 0
            self.action_count = 0
        self.root.after(6000, self.check_and_trigger_wagging)

    def check_and_trigger_tongue(self):
        # Allow idle animations even if LeetCode question is active
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

        width = 200
        pending_count = self.leetcode_scraper.get_pending_count()
        ask_label = f"Ask Now ({pending_count} revision{'s' if pending_count != 1 else ''})"
        
        menu_items = [
            ("ITEM", "Sleep", self.on_sleep_click),
            ("ITEM", "Surprise me!", self.on_surprise_click),
            ("ITEM", "OCR", self.on_ocr_click),
            ("HEADER", "LEETCODE", None),
            ("ITEM", "Enter Profile", self.on_leetcode_profile_click),
            ("ITEM", ask_label, self.on_leetcode_ask_click),
            ("ITEM", "Clear Revisions", self.on_leetcode_clear_click)
        ]
        
        # Calculate dynamic height
        height = 0
        for m_type, _, _ in menu_items:
            height += 40 if m_type == "HEADER" else 35
            
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

        current_y = 0
        hover_data = {}
        
        for m_type, text, cmd in menu_items:
            if m_type == "HEADER":
                h = 40
                # Left-aligned and slightly bigger
                canvas.create_text(15, current_y + h // 2, text=text, fill="#4A2F13", font=("Arial", 13, "bold"), anchor="w")
            else:
                h = 35
                fg_color = "#8B0000" if text == "Clear Revisions" else "#4A2F13"
                text_id = canvas.create_text(width // 2, current_y + h // 2, text=text, fill=fg_color, font=("Arial", 10))
                hover_data[current_y] = {"y1": current_y, "y2": current_y + h, "text_id": text_id, "cmd": cmd, "fg": fg_color}
            current_y += h

        def on_motion(e):
            y = e.y
            found = False
            for y_start, data in hover_data.items():
                if data["y1"] <= y <= data["y2"]:
                    found = True
                    if not hasattr(canvas, "_hover_rect") or canvas._hover_rect is None or canvas._hover_rect_y != y_start:
                        if hasattr(canvas, "_hover_rect") and canvas._hover_rect:
                            canvas.delete(canvas._hover_rect)
                            if hasattr(canvas, "_hover_rect_tid"):
                                canvas.itemconfig(canvas._hover_rect_tid, fill=canvas._hover_rect_fg)
                        
                        r = 8
                        x1, y1, x2, y2 = 5, data["y1"]+3, width-5, data["y2"]-3
                        points = [
                            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
                            x2, y2-r, x2, y2, x2-r, y2,
                            x1+r, y2, x1, y2, x1, y2-r, x1, y1+r,
                            x1, y1
                        ]
                        rect = canvas.create_polygon(points, smooth=True, fill="#8B5A2B", outline="")
                        canvas.tag_lower(rect)
                        canvas.itemconfig(data["text_id"], fill="white")
                        
                        canvas._hover_rect = rect
                        canvas._hover_rect_y = y_start
                        canvas._hover_rect_tid = data["text_id"]
                        canvas._hover_rect_fg = data["fg"]
                    break
            
            if not found:
                if hasattr(canvas, "_hover_rect") and canvas._hover_rect:
                    canvas.delete(canvas._hover_rect)
                    canvas._hover_rect = None
                    if hasattr(canvas, "_hover_rect_tid"):
                        canvas.itemconfig(canvas._hover_rect_tid, fill=canvas._hover_rect_fg)

        def on_click(e):
            y = e.y
            for y_start, data in hover_data.items():
                if data["y1"] <= y <= data["y2"]:
                    data["cmd"]()
                    self.close_context_menu()
                    break

        def on_leave(e):
            if hasattr(canvas, "_hover_rect") and canvas._hover_rect:
                canvas.delete(canvas._hover_rect)
                canvas._hover_rect = None
                if hasattr(canvas, "_hover_rect_tid"):
                    canvas.itemconfig(canvas._hover_rect_tid, fill=canvas._hover_rect_fg)

        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<Button-1>", on_click)

        self.context_menu.focus_set()
        self.context_menu.bind("<FocusOut>", lambda e: self.close_context_menu())
        self.root.bind("<ButtonPress-1>", lambda e: self.close_context_menu(), add="+")

    def close_context_menu(self):
        if self.context_menu:
            try: self.context_menu.destroy()
            except: pass
            self.context_menu = None

    def is_asleep(self):
        return self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]

    def on_sleep_click(self):
        if self.current_state in ["walking_down", "sleeping_phase1", "sleeping_phase2", "sleeping_phase3", "walking_up"]: return
        if self.ocr_waiting or self.ocr_processing or self.leetcode_question_active: return
        self.start_sleep_flow()

    def on_surprise_click(self):
        if self.is_asleep() or self.surprise_active: return
        if self.ocr_waiting or self.ocr_processing or self.leetcode_question_active: return
        self.start_surprise_flow()

    def load_random_website_url(self):
        websites_file = os.path.join(self.base_dir, "Random Websites.txt")
        with open(websites_file, "r", encoding="utf-8") as file:
            urls = [line.strip() for line in file if line.strip()]
        if not urls: raise ValueError("No websites found")
        return random.choice(urls)

    def start_surprise_flow(self):
        if not self.frames.get("surprise"):
            self.finish_surprise_flow()
            return
        self.surprise_active = True
        self.current_state = "surprise"
        self.current_frame = 0
        self.action_count = 0

    def finish_surprise_flow(self):
        try: webbrowser.open(self.load_random_website_url())
        except: pass
        finally: self.surprise_active = False

    def start_sleep_flow(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        current_x = self.root.winfo_x()
        self.walk_target_x = 0 if current_x >= screen_width / 2 else screen_width - 150
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
            if self.current_state not in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]: return
            if count > steps:
                callback()
                return
            blended = Image.blend(start_pil, end_pil, count / steps)
            r, g, b, a = blended.split()
            blended.putalpha(a.point(lambda p: 255 if p > 128 else 0))
            self.fade_photo = ImageTk.PhotoImage(blended)
            self.label.config(image=self.fade_photo)
            self.root.after(interval, lambda: step(count + 1))
        step(0)

    def enter_sleep_state(self):
        if self.sleep_timer: self.root.after_cancel(self.sleep_timer)
        self.current_state = "sleeping_phase1"
        self.current_frame = 0
        walk_key = getattr(self, "walk_sprite_key", "walking_right")
        w_idx = min(self.current_frame, len(self.pil_frames[walk_key]) - 1)
        start_img = self.pil_frames[walk_key][w_idx]
        end_img = self.pil_frames["sleeping"][0]
        self.fade_transition(start_img, end_img, 800, lambda: setattr(self, "sleep_timer", self.root.after(2200, self.enter_sleep_phase2)))

    def enter_sleep_phase2(self):
        self.current_state = "sleeping_phase2"
        self.current_frame = 1
        self.fade_transition(self.pil_frames["sleeping"][0], self.pil_frames["sleeping"][1], 800, lambda: setattr(self, "sleep_timer", self.root.after(4200, self.enter_sleep_phase3)))

    def enter_sleep_phase3(self):
        self.current_state = "sleeping_phase3"
        self.current_frame = 2
        self.sleep_timer = None
        self.fade_transition(self.pil_frames["sleeping"][1], self.pil_frames["sleeping"][2], 800, self.start_zzz_loop)

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
        lbl = tk.Label(z_win, text=random.choice(["z", "Z", "zZ"]), bg=z_bg, fg=random.choice(["#9370DB", "#8A2BE2", "#4B0082"]), font=("Comic Sans MS", random.randint(10, 16), "bold"))
        lbl.pack()
        rx, ry = self.root.winfo_x() + 45 + random.randint(-15, 15), self.root.winfo_y() + 25 + random.randint(-10, 10)
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
            try: win.geometry(f"+{x + int(random.choice([-2, -1, 0, 1, 2]))}+{y - 3}")
            except: return
            self.root.after(50, lambda: drift(win, x + int(random.choice([-2, -1, 0, 1, 2])), y - 3, age + 1))
        drift(z_win, rx, ry)
        self.zzz_timer = self.root.after(1200, self.spawn_zzz)

    def cleanup_zzz(self):
        if hasattr(self, "zzz_timer") and self.zzz_timer:
            try: self.root.after_cancel(self.zzz_timer)
            except: pass
            self.zzz_timer = None
        for win in self.zzz_windows:
            try: win.destroy()
            except: pass
        self.zzz_windows = []

    def wake_up(self):
        self.cleanup_zzz()
        if self.sleep_timer:
            try: self.root.after_cancel(self.sleep_timer)
            except: pass
            self.sleep_timer = None
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.walk_target_x = random.randint(int(screen_w * 0.6), max(int(screen_w * 0.6) + 1, int(screen_w * 0.9) - 150))
        self.walk_target_y = random.randint(10, max(11, int(screen_h * 0.6) - 150))
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
        if self.is_asleep() or self.surprise_active or self.ocr_processing or self.ocr_waiting or self.leetcode_question_active: return
        if not self.ocr_engine.available:
            self.ocr_ui.show_bubble("OCR not available!", 2500)
            return
        self.ocr_waiting = True
        self.ocr_ui.show_bubble("Paste the image!")

    def on_ctrl_v(self, event):
        if not self.ocr_waiting: return 
        if self.is_asleep() or self.surprise_active or self.ocr_processing or self.leetcode_question_active:
            self.ocr_waiting = False
            return "break"
        if not self.ocr_engine.available:
            self.ocr_waiting = False
            self.ocr_ui.show_bubble("OCR not available!", 2500)
            return "break"
        self.start_ocr_processing()
        return "break"

    def on_ctrl_shift_v(self, event):
        if self.is_asleep() or self.surprise_active or self.ocr_processing or self.ocr_waiting or self.leetcode_question_active: return "break"
        if not self.ocr_engine.available:
            self.ocr_ui.show_bubble("OCR not available!", 2500)
            return "break"
        self.start_ocr_processing()
        return "break"

    def start_ocr_processing(self):
        self.ocr_waiting = False
        self.ocr_processing = True
        if self.frames.get("ocr_animation"):
            self.current_state = "ocr_animation"
            self.current_frame = 0
        self.ocr_ui.show_bubble("Scanning...")
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
        except: pass
        if len(text) > 100:
            self.ocr_ui.show_bubble(f"Found {len(text)} characters!")
            self.root.after(1500, lambda: self.ocr_ui.show_result_popup(text, len(text)))
            self.root.after(5000, self._reset_ocr_state)
        else:
            self.ocr_ui.show_bubble(text, 2000)
            self.root.after(2000, lambda: self.ocr_ui.show_bubble("Mission complete!", 3500))
            self.root.after(5500, self._reset_ocr_state)

    def _reset_ocr_state(self):
        self.ocr_waiting = False
        self.ocr_processing = False
        self.ocr_ui.hide_bubble()
        self.current_state = "default"
        self.current_frame = 0
        self.action_count = 0

    # =================================================================
    # LEETCODE FLOW METHODS
    # =================================================================
    def on_leetcode_profile_click(self):
        current = self.leetcode_scraper.get_profile()
        username = simpledialog.askstring("LeetCode Profile", "Enter your LeetCode username:", initialvalue=current)
        if username is not None and username.strip():
            self.leetcode_scraper.set_profile(username.strip())
            self.ocr_ui.show_bubble("Profile saved!", 2000)


    def auto_sync_leetcode(self):
        if self.leetcode_scraper.get_profile():
            self.leetcode_scraper.sync(callback=self.on_auto_sync_complete)
        self.root.after(AUTO_SYNC_INTERVAL_MIN * 60000, self.auto_sync_leetcode)

    def on_auto_sync_complete(self, success, msg):
        if success and "auto-completed" in msg:
            self.root.after(0, lambda: self.ocr_ui.show_bubble("LeetCode Auto-Sync: Problem Solved!", 3000))
            self.leetcode_scraper.process_queue(callback=self.on_process_queue_complete)

    def on_leetcode_ask_click(self):
        if self.leetcode_question_active or self.ocr_processing or self.surprise_active:
            self.ocr_ui.show_bubble("Busy right now!", 2000)
            return
        self.ocr_ui.show_bubble("Fetching a question...", 5000)
        self.leetcode_scraper.force_ask(callback=self.on_force_ask_complete)

    def on_leetcode_clear_click(self):
        if messagebox.askyesno("Clear All Revisions", "WARNING: This will permanently delete ALL tracked, queued, and completed LeetCode questions from your local database.\n\nThis action CANNOT be undone.\n\nAre you absolutely sure you want to clear everything?"):
            self.leetcode_scraper.clear_all_revisions()
            self.ocr_ui.show_bubble("Revisions cleared!", 2000)


    def check_leetcode_queue(self):
        if not self.leetcode_question_active and not self.ocr_processing and not self.surprise_active:
            self.leetcode_scraper.process_queue(callback=self.on_process_queue_complete)
        self.root.after(60000, self.check_leetcode_queue)

    def on_process_queue_complete(self, success, question):
        if success and question:
            self.root.after(0, lambda: self.trigger_leetcode_question(question))

    def on_force_ask_complete(self, success, question):
        if success and question:
            self.root.after(0, lambda: self.trigger_leetcode_question(question))
        else:
            self.root.after(0, lambda: self.ocr_ui.show_bubble("No questions tracked! Sync first.", 3000))

    def trigger_leetcode_question(self, question):
        if self.leetcode_question_active: return
        
        if self.is_asleep():
            self.wake_up()
            self.root.after(3000, lambda: self._show_leetcode_question(question))
            return

        if self.current_state in ["walking_down", "walking_up", "surprise"]:
            self.root.after(2000, lambda: self.trigger_leetcode_question(question))
            return

        self._show_leetcode_question(question)

    def _show_leetcode_question(self, question):
        self.leetcode_question_active = True
        self.ocr_ui.hide_bubble() # HIDE THE FETCHING BUBBLE IMMEDIATELY
        self.show_leetcode_preview_blob(question)

    def show_leetcode_preview_blob(self, q):
        self.hide_leetcode_preview_blob()
        self.leetcode_preview_win = tk.Toplevel(self.root)
        self.leetcode_preview_win.overrideredirect(True)
        self.leetcode_preview_win.config(bg="#FFF8DC")
        self.leetcode_preview_win.attributes("-topmost", True)

        pet_x = self.root.winfo_x()
        pet_y = self.root.winfo_y()
        self.leetcode_preview_win.geometry(f"+{pet_x}+{pet_y}")

        c = tk.Canvas(self.leetcode_preview_win, bg="#FFF8DC", highlightthickness=0, bd=0, width=280, height=140)
        c.pack(fill="both", expand=True)
        c.create_rectangle(2, 2, 278, 138, outline="#4A2F13", width=3)
        c.create_rectangle(6, 6, 274, 134, outline="#D2B48C", width=1)

        c.create_text(140, 20, text=q["title"], fill="#4A2F13", font=("Arial", 10, "bold"), width=260)

        review_stage = q.get("review_stage", 1)
        if review_stage == 1:
            review_text = "Review #1 (10 days after solving)"
        else:
            review_text = f"Review #{review_stage} (30 days after completion)"
        c.create_text(140, 38, text=review_text, fill="#8B5A2B", font=("Arial", 7, "italic"))

        desc = q["description"][:100] + "..." if len(q["description"]) > 100 else q["description"]
        c.create_text(140, 75, text=desc, fill="#4A2F13", font=("Arial", 8), width=260, justify="center")

        btn_frame = tk.Frame(self.leetcode_preview_win, bg="#FFF8DC")
        c.create_window(140, 115, window=btn_frame)
        
        tk.Button(btn_frame, text="View More", bg="#D2B48C", fg="#4A2F13", font=("Arial", 7, "bold"), relief="flat", 
                  command=lambda: self.open_full_leetcode_popup(q)).pack(side="left", padx=3)
        tk.Button(btn_frame, text="Later", bg="#D2B48C", fg="#4A2F13", font=("Arial", 7, "bold"), relief="flat", 
                  command=lambda: self.handle_leetcode_later(q)).pack(side="left", padx=3)
        tk.Button(btn_frame, text="Complete?", bg="#D2B48C", fg="#4A2F13", font=("Arial", 7, "bold"), relief="flat", 
                  command=lambda: self.handle_leetcode_complete(q)).pack(side="left", padx=3)

        self.leetcode_preview_win.update_idletasks()

    def hide_leetcode_preview_blob(self):
        if self.leetcode_preview_win:
            try: self.leetcode_preview_win.destroy()
            except: pass
            self.leetcode_preview_win = None

    def open_full_leetcode_popup(self, q):
        self.ocr_ui.hide_bubble()
        self.hide_leetcode_preview_blob()
        self.show_leetcode_full_popup(q)

    def show_leetcode_full_popup(self, q):
        self.leetcode_popup = tk.Toplevel(self.root)
        self.leetcode_popup.title("LeetCode Review")
        self.leetcode_popup.config(bg="#FFF8DC")
        self.leetcode_popup.attributes("-topmost", True)
        
        pw, ph = 600, 550
        sw, sh = self.leetcode_popup.winfo_screenwidth(), self.leetcode_popup.winfo_screenheight()
        self.leetcode_popup.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")

        c = tk.Canvas(self.leetcode_popup, bg="#FFF8DC", highlightthickness=0, bd=0, width=pw, height=ph)
        c.pack(fill="both", expand=True)
        c.create_rectangle(3, 3, pw-3, ph-3, outline="#4A2F13", width=5)
        c.create_rectangle(10, 10, pw-10, ph-10, outline="#D2B48C", width=2)

        c.create_window(pw//2, 40, window=tk.Label(c, text=q["title"], bg="#FFF8DC", fg="#4A2F13", font=("Arial", 14, "bold")))
        
        review_stage = q.get("review_stage", 1)
        if review_stage == 1:
            review_text = "Review #1 (10 days after solving)"
        else:
            review_text = f"Review #{review_stage} (30 days after completion)"
            
        c.create_window(pw//2, 65, window=tk.Label(c, text=review_text, bg="#FFF8DC", fg="#8B5A2B", font=("Arial", 10, "italic")))
        
        text_holder = tk.Frame(c, bg="#4A2F13", bd=0, width=560, height=350)
        text_holder.pack_propagate(False)
        st = scrolledtext.ScrolledText(text_holder, wrap=tk.WORD, bg="#D2B48C", fg="#4A2F13", font=("Arial", 10), relief="flat")
        st.pack(fill="both", expand=True, padx=3, pady=3)
        st.insert("1.0", f"DESCRIPTION:\n{q['description']}\n\nEXAMPLE INPUT:\n{q['example_input']}\n\nEXAMPLE OUTPUT:\n{q['example_output']}")
        st.config(state="disabled")
        c.create_window(pw//2, 245, window=text_holder)

        btn_frame = tk.Frame(c, bg="#FFF8DC")
        c.create_window(pw//2, 480, window=btn_frame)
        
        tk.Button(btn_frame, text="Later", bg="#D2B48C", fg="#4A2F13", font=("Arial", 10, "bold"), relief="flat", 
                  command=lambda: self.handle_leetcode_later(q)).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Let's Try", bg="#D2B48C", fg="#4A2F13", font=("Arial", 10, "bold"), relief="flat", 
                  command=lambda: self.handle_leetcode_try(q)).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Completed", bg="#D2B48C", fg="#4A2F13", font=("Arial", 10, "bold"), relief="flat", 
                  command=lambda: self.handle_leetcode_complete(q)).pack(side="left", padx=10)

        self.leetcode_popup.protocol("WM_DELETE_WINDOW", lambda: self.handle_leetcode_later(q))

    def handle_leetcode_later(self, q):
        self.ocr_ui.hide_bubble()
        self.hide_leetcode_preview_blob()
        try: self.leetcode_popup.destroy()
        except: pass
        self.leetcode_popup = None
        
        self.leetcode_scraper.action_later(q)
        self._reset_leetcode_state()

    def handle_leetcode_try(self, q):
        self.ocr_ui.hide_bubble()
        self.hide_leetcode_preview_blob()
        try: self.leetcode_popup.destroy()
        except: pass
        self.leetcode_popup = None
        
        self.leetcode_scraper.action_try(q)
        self.leetcode_try_url = q["url"]
        
        if self.frames.get("dsa_randomwebsite"):
            self.current_state = "dsa_randomwebsite"
            self.current_frame = 0
        else:
            if self.leetcode_try_url:
                webbrowser.open(self.leetcode_try_url)
                self.leetcode_try_url = None
            self._reset_leetcode_state()

    def handle_leetcode_complete(self, q):
        self.ocr_ui.hide_bubble()
        self.hide_leetcode_preview_blob()
        try: self.leetcode_popup.destroy()
        except: pass
        self.leetcode_popup = None
        
        self.leetcode_scraper.action_complete(q)
        self._reset_leetcode_state()

    def _reset_leetcode_state(self):
        self.leetcode_question_active = False
        self.current_state = "default"
        self.current_frame = 0
        self.action_count = 0

    # =================================================================
    # MAIN ANIMATION LOOP
    # =================================================================
    def animate(self):
        frame_key = self.current_state
        if self.current_state in ["walking_down", "walking_up"]:
            frame_key = getattr(self, "walk_sprite_key", "walking_right")
        elif self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            frame_key = "sleeping"

        state_frames = self.frames.get(frame_key)

        if state_frames:
            if self.current_state == "sleeping_phase1": self.current_frame = 0
            elif self.current_state == "sleeping_phase2": self.current_frame = 1
            elif self.current_state == "sleeping_phase3": self.current_frame = 2

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

                if self.current_state == "dsa_randomwebsite":
                    if self.current_frame < len(state_frames) - 1:
                        self.current_frame += 1
                    else:
                        if self.leetcode_try_url:
                            webbrowser.open(self.leetcode_try_url)
                            self.leetcode_try_url = None
                        self._reset_leetcode_state()
                        
                elif self.current_state == "ocr_animation":
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
                            if self.current_state == "surprise": self.finish_surprise_flow()
                            self.current_state = "default"
                            self.action_count = 0
                elif self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
                    pass
                else:
                    self.current_frame = (self.current_frame + 1) % len(state_frames)

            if self.current_state == "walking_down":
                dx, dy = self.walk_target_x - self.pos_x, self.walk_target_y - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5
                if dist > self.walk_speed:
                    self.pos_x += (dx / dist) * self.walk_speed
                    self.pos_y += (dy / dist) * self.walk_speed
                    self.root.geometry(f"+{round(self.pos_x)}+{round(self.pos_y + math.sin(time.time() * self.bob_frequency) * self.bob_amplitude)}")
                else:
                    self.root.geometry(f"+{self.walk_target_x}+{self.walk_target_y}")
                    self.pos_x, self.pos_y = float(self.walk_target_x), float(self.walk_target_y)
                    self.enter_sleep_state()

            elif self.current_state == "walking_up":
                dx, dy = self.walk_target_x - self.pos_x, self.walk_target_y - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5
                if dist > self.walk_speed:
                    self.pos_x += (dx / dist) * self.walk_speed
                    self.pos_y += (dy / dist) * self.walk_speed
                    self.root.geometry(f"+{round(self.pos_x)}+{round(self.pos_y + math.sin(time.time() * self.bob_frequency) * self.bob_amplitude)}")
                else:
                    self.root.geometry(f"+{self.walk_target_x}+{self.walk_target_y}")
                    self.pos_x, self.pos_y = float(self.walk_target_x), float(self.walk_target_y)
                    self.current_state = "default"
                    self.current_frame = 0

        self.ocr_ui.update_pet_pos(self.root.winfo_x(), self.root.winfo_y())
        
        # Keep LeetCode preview blob stuck to pet
        if self.leetcode_preview_win:
            self.leetcode_preview_win.update_idletasks()
            w = self.leetcode_preview_win.winfo_reqwidth()
            h = self.leetcode_preview_win.winfo_reqheight()
            x = self.root.winfo_x() + 75 - w // 2
            y = self.root.winfo_y() - h - 10
            if y < 0: y = self.root.winfo_y() + 150 + 10
            if x < 0: x = 0
            sw = self.root.winfo_screenwidth()
            if x + w > sw: x = sw - w
            try:
                self.leetcode_preview_win.geometry(f"+{x}+{y}")
            except: pass

        self.root.after(16, self.animate)

    def start_move(self, event):
        # Allow dragging even if LeetCode question is active
        if self.ocr_processing or self.ocr_waiting: return
        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            self.x, self.y = event.x, event.y
            self.is_dragging = False
            return
        if self.current_state in ["walking_down", "walking_up", "surprise", "ocr_animation", "dsa_randomwebsite"]: return
        self.x, self.y = event.x, event.y
        self.is_dragging = False

    def do_move(self, event):
        # Allow dragging even if LeetCode question is active
        if self.ocr_processing or self.ocr_waiting: return
        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            self.is_dragging = True
            x = self.root.winfo_x() + (event.x - self.x)
            y = self.root.winfo_y()
            self.root.geometry(f"+{x}+{y}")
            self.pos_x, self.pos_y = float(x), float(y)
            return
        if self.current_state in ["walking_down", "walking_up", "surprise", "ocr_animation", "dsa_randomwebsite"]: return
        if not self.is_dragging:
            self.is_dragging = True
            self.current_state = "lift"
            self.current_frame = 0
        x = self.root.winfo_x() + (event.x - self.x)
        y = self.root.winfo_y() + (event.y - self.y)
        self.root.geometry(f"+{x}+{y}")
        self.pos_x, self.pos_y = float(x), float(y)

    def stop_move(self, event):
        # Allow dragging even if LeetCode question is active
        if self.ocr_processing or self.ocr_waiting: return
        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            if self.current_state == "sleeping_phase3" and not self.is_dragging: self.wake_up()
            self.is_dragging = False
            return
        if self.current_state in ["walking_down", "walking_up", "surprise", "ocr_animation", "dsa_randomwebsite"]: return
        if not self.is_dragging and self.current_state == "default":
            if random.choice([True, False]): self.current_state = "pat_pat"
            else: self.current_state = "hi"
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