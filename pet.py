import tkinter as tk
from PIL import Image, ImageTk
import os
import random

class DesktopPet:
    def __init__(self, root, default_folder, wagging_folder, lift_folder, hi_folder):
        self.root = root
        
        # --- WINDOW CONFIGURATION ---
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.transparent_color = '#000001'
        self.root.config(bg=self.transparent_color)
        self.root.attributes("-transparentcolor", self.transparent_color)
        
        # --- STATE INITIALIZATION ---
        self.frames = {
            "default": self.load_frames(default_folder),
            "wagging": self.load_frames(wagging_folder),
            "lift": self.load_frames(lift_folder),
            "hi": self.load_frames(hi_folder)
        }
        self.current_state = "default"
        self.current_frame = 0
        self.x, self.y = 0, 0
        self.is_dragging = False
        self.action_count = 0  # Counter for playback loops
        
        self.label = tk.Label(root, bg=self.transparent_color, borderwidth=0, highlightthickness=0)
        self.label.pack()
        
        self.animate()

        self.label.bind("<ButtonPress-1>", self.start_move)
        self.label.bind("<B1-Motion>", self.do_move)
        self.label.bind("<ButtonRelease-1>", self.stop_move)

    def load_frames(self, folder_path):
        frames = []
        files = sorted([f for f in os.listdir(folder_path) if f.endswith(".png")])
        for file in files:
            path = os.path.join(folder_path, file)
            img = Image.open(path).convert('RGBA').resize((250, 250), Image.Resampling.LANCZOS)
            alpha = img.split()[-1].point(lambda p: 255 if p > 128 else 0)
            img.putalpha(alpha)
            frames.append(ImageTk.PhotoImage(img))
        return frames

    def animate(self):
        state_frames = self.frames[self.current_state]
        if state_frames:
            self.label.config(image=state_frames[self.current_frame])
            
            # --- ANIMATION LOGIC ---
            if self.current_state in ["wagging", "hi"]:
                if self.current_frame < len(state_frames) - 1:
                    self.current_frame += 1
                else:
                    self.current_frame = 0
                    self.action_count += 1
                    
                    # wagging plays 3 times, hi plays 4 times
                    limit = 3 if self.current_state == "wagging" else 4
                    
                    if self.action_count >= limit:
                        self.current_state = "default"
                        self.action_count = 0
            else:
                self.current_frame = (self.current_frame + 1) % len(state_frames)
            
            self.root.after(100, self.animate)

    def start_move(self, event):
        self.x, self.y = event.x, event.y
        self.is_dragging = False 

    def do_move(self, event):
        if not self.is_dragging:
            self.is_dragging = True
            self.current_state = "lift"
            self.current_frame = 0
            
        x = self.root.winfo_x() + (event.x - self.x)
        y = self.root.winfo_y() + (event.y - self.y)
        self.root.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        if not self.is_dragging and self.current_state == "default":
            # --- RANDOM ACTION LOGIC ---
            if random.choice([True, False]):
                self.current_state = "wagging"
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
    # Ensure you have 'default', 'wagging', 'lift', and 'hi' folders
    pet_app = DesktopPet(root, "default", "wagging", "lift", "hi")
    root.mainloop()