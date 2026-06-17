import tkinter as tk
from PIL import Image, ImageTk
import os
import random
import time
import math  # <-- Added for the sine wave bobbing effect

class DesktopPet:
    def __init__(self, root, default_folder, wagging_folder, lift_folder, hi_folder, tongue_folder, 
                 pat_pat_folder="pat-pat", walking_folder="WALKING", sleeping_folder="Sleeping"):
        self.root = root
        
        # --- WINDOW CONFIGURATION ---
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.transparent_color = '#000001'
        self.root.config(bg=self.transparent_color)
        self.root.attributes("-transparentcolor", self.transparent_color)
        
        # --- STATE INITIALIZATION ---
        self.pil_frames = {}
        self.frames = {
            "default": self.load_frames(default_folder),
            "wagging": self.load_frames(wagging_folder),
            "lift": self.load_frames(lift_folder),
            "hi": self.load_frames(hi_folder),
            "tongue": self.load_frames(tongue_folder),
            "pat_pat": self.load_frames(pat_pat_folder),
            "walking": self.load_frames(walking_folder, save_pil_key="walking"),
            "walking_flipped": self.load_frames(walking_folder, flip=True, save_pil_key="walking_flipped"),
            "sleeping": self.load_frames(sleeping_folder, save_pil_key="sleeping")
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
        
        # --- SMOOTH MOVEMENT & TIMING VARIABLES ---
        self.walk_speed = 3.0  # How fast the pet glides across the screen
        self.pos_x = float(self.root.winfo_x())
        self.pos_y = float(self.root.winfo_y())
        self.last_frame_time = time.time()
        
        # --- ANIMATION SPEEDS (Seconds per frame) ---
        self.normal_anim_speed = 0.1  # 100ms for wagging, hi, tongue, etc.
        self.walk_anim_speed = 0.04   # 40ms for faster walking animation!
        
        # --- BOBBING EFFECT CONFIGURATION ---
        self.bob_amplitude = 8.0      # How many pixels up/down the pet moves
        self.bob_frequency = 18.0     # How fast the up/down bounce cycles
        
        self.label = tk.Label(root, bg=self.transparent_color, borderwidth=0, highlightthickness=0)
        self.label.pack()
        
        self.animate()
        self.root.after(6000, self.check_and_trigger_wagging)
        self.root.after(1000, self.check_and_trigger_tongue)

        self.label.bind("<ButtonPress-1>", self.start_move)
        self.label.bind("<B1-Motion>", self.do_move)
        self.label.bind("<ButtonRelease-1>", self.stop_move)
        self.label.bind("<Button-3>", self.show_context_menu)

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

    def check_and_trigger_wagging(self):
        if self.current_state == "default":
            self.current_state = "wagging"
            self.current_frame = 0
            self.action_count = 0
        self.root.after(6000, self.check_and_trigger_wagging)

    def check_and_trigger_tongue(self):
        if self.current_state == "default":
            self.current_state = "tongue"
            self.current_frame = 0
            self.action_count = 0
        self.root.after(1000, self.check_and_trigger_tongue)

    def show_context_menu(self, event):
        self.close_context_menu()
        
        self.context_menu = tk.Toplevel(self.root)
        self.context_menu.overrideredirect(True)
        self.context_menu.config(bg="#5C4033")
        self.context_menu.attributes("-topmost", True)
        
        self.context_menu.geometry(f"+{event.x_root}+{event.y_root}")
        
        inner = tk.Frame(self.context_menu, bg="#D2B48C")
        inner.pack(padx=1, pady=1)
        
        sleep_item = tk.Label(inner, text="Sleep", bg="#D2B48C", fg="#4A2F13", font=("Arial", 10), padx=15, pady=5, cursor="hand2")
        sleep_item.pack()
        
        sleep_item.bind("<Enter>", lambda e: sleep_item.config(bg="#8B5A2B", fg="white"))
        sleep_item.bind("<Leave>", lambda e: sleep_item.config(bg="#D2B48C", fg="#4A2F13"))
        sleep_item.bind("<Button-1>", lambda e: self.on_sleep_click())
        
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

    def on_sleep_click(self):
        self.close_context_menu()
        if self.current_state in ["walking_down", "sleeping_phase1", "sleeping_phase2", "sleeping_phase3", "walking_up"]:
            return
        self.start_sleep_flow()

    def start_sleep_flow(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        current_x = self.root.winfo_x()
        
        if current_x >= screen_width / 2:
            self.walk_target_x = 0
        else:
            self.walk_target_x = screen_width - 150
            
        self.walk_target_y = screen_height - 150
        self.walk_flip = (self.walk_target_x > current_x)
        
        # Sync floats for movement
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
        
        walk_key = "walking_flipped" if getattr(self, "walk_flip", False) else "walking"
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
        
        self.walk_flip = (self.walk_target_x > self.root.winfo_x())
        
        # Sync floats for movement
        self.pos_x = float(self.root.winfo_x())
        self.pos_y = float(self.root.winfo_y())
        
        self.current_state = "walking_up"
        self.current_frame = 0

    def animate(self):
        # Resolve frame mapping
        frame_key = self.current_state
        if self.current_state in ["walking_down", "walking_up"]:
            frame_key = "walking_flipped" if getattr(self, "walk_flip", False) else "walking"
        elif self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            frame_key = "sleeping"

        state_frames = self.frames.get(frame_key)
        
        if state_frames:
            # Set explicit frames for sleeping states
            if self.current_state == "sleeping_phase1":
                self.current_frame = 0
            elif self.current_state == "sleeping_phase2":
                self.current_frame = 1
            elif self.current_state == "sleeping_phase3":
                self.current_frame = 2

            if self.current_state not in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
                self.label.config(image=state_frames[self.current_frame])
            
            # --- ANIMATION LOGIC (Regulated by state-specific timers) ---
            if self.current_state in ["walking_down", "walking_up"]:
                current_delay = self.walk_anim_speed
            else:
                current_delay = self.normal_anim_speed

            current_time = time.time()
            if current_time - self.last_frame_time >= current_delay:
                self.last_frame_time = current_time
                
                if self.current_state in ["wagging", "hi", "tongue", "pat_pat"]:
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
                            self.current_state = "default"
                            self.action_count = 0
                elif self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
                    pass
                else:
                    self.current_frame = (self.current_frame + 1) % len(state_frames)

            # --- MOVEMENT LOGIC (Runs every 16ms for 60FPS physics) ---
            if self.current_state == "walking_down":
                dx = self.walk_target_x - self.pos_x
                dy = self.walk_target_y - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5
                
                if dist > self.walk_speed:
                    self.pos_x += (dx / dist) * self.walk_speed
                    self.pos_y += (dy / dist) * self.walk_speed
                    # Apply up and down sine-wave bobbing effect
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
                    # Apply up and down sine-wave bobbing effect
                    bob_offset = math.sin(time.time() * self.bob_frequency) * self.bob_amplitude
                    self.root.geometry(f"+{round(self.pos_x)}+{round(self.pos_y + bob_offset)}")
                else:
                    self.root.geometry(f"+{self.walk_target_x}+{self.walk_target_y}")
                    self.pos_x, self.pos_y = float(self.walk_target_x), float(self.walk_target_y)
                    self.current_state = "default"
                    self.current_frame = 0
            
        self.root.after(16, self.animate)

    def start_move(self, event):
        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            self.x = event.x
            self.y = event.y
            self.is_dragging = False
            return
        if self.current_state in ["walking_down", "walking_up"]:
            return
        self.x, self.y = event.x, event.y
        self.is_dragging = False 

    def do_move(self, event):
        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            self.is_dragging = True
            x = self.root.winfo_x() + (event.x - self.x)
            y = self.root.winfo_y() 
            self.root.geometry(f"+{x}+{y}")
            self.pos_x = float(x)
            self.pos_y = float(y)
            return
            
        if self.current_state in ["walking_down", "walking_up"]:
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
        if self.current_state in ["sleeping_phase1", "sleeping_phase2", "sleeping_phase3"]:
            if self.current_state == "sleeping_phase3" and not self.is_dragging:
                self.wake_up()
            self.is_dragging = False
            return
        if self.current_state in ["walking_down", "walking_up"]:
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