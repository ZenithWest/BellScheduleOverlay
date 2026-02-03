import sys
import os
import platform
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple

# ----------------------------
# Schedule parsing
# ----------------------------

@dataclass
class Item:
    title: str
    t1: time              # begin time (or the only time if single)
    t2: Optional[time]    # end time (None if single-time line)

def parse_hhmm(s: str) -> time:
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"Bad time '{s}', expected HH:MM")
    h = int(parts[0])
    m = int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Bad time '{s}', out of range")
    return time(hour=h, minute=m)

def load_schedule(path: str) -> List[Item]:
    items: List[Item] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f.readlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",")]

            if len(parts) == 2:
                title, t = parts
                items.append(Item(title=title, t1=parse_hhmm(t), t2=None))
            elif len(parts) >= 3:
                title, t1, t2 = parts[0], parts[1], parts[2]
                items.append(Item(title=title, t1=parse_hhmm(t1), t2=parse_hhmm(t2)))
            else:
                continue

    if not items:
        raise ValueError("No schedule items found.")
    return items

# ----------------------------
# Timeline logic
# ----------------------------

def dt_today(t: time) -> datetime:
    return datetime.combine(date.today(), t)

def last_time_of(item: Item) -> time:
    return item.t2 if item.t2 is not None else item.t1

def next_begin_of(items: List[Item], idx: int) -> Optional[time]:
    if idx + 1 >= len(items):
        return None
    return items[idx + 1].t1

def fmt_hhmmss(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    h = total // 3600
    rem = total % 3600
    m = rem // 60
    s = rem % 60
    return f"{h:d}:{m:02d}:{s:02d}"

def compute_display(items: List[Item], now: datetime) -> Tuple[str, Optional[str]]:
    for i, item in enumerate(items):
        begin = dt_today(item.t1)
        end = dt_today(item.t2) if item.t2 else None

        if end is None:
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)
            else:
                nxt = next_begin_of(items, i)
                if nxt is not None:
                    nxt_dt = dt_today(nxt)
                    if begin <= now < nxt_dt:
                        return f"Transitioning from {item.title} to {items[i+1].title}", None
        else:
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)
            elif begin <= now < end:
                return item.title, fmt_hhmmss(end - now)
            else:
                nxt = next_begin_of(items, i)
                if nxt is not None:
                    nxt_dt = dt_today(nxt)
                    if end <= now < nxt_dt:
                        return f"Transitioning from {item.title} to {items[i+1].title}", None

    last_item = items[-1]
    last_dt = dt_today(last_time_of(last_item))
    if now >= last_dt:
        return "End of School", fmt_hhmmss(now - last_dt)

    return "Schedule", None

# ----------------------------
# Windows click-through helper
# ----------------------------

def is_windows() -> bool:
    return platform.system().lower() == "windows"

def _try_enable_clickthrough(hwnd: int, enable: bool) -> None:
    """
    Windows-only:
    enable=True  => click-through (mouse passes to windows underneath)
    enable=False => normal (can interact with overlay)
    """
    if not is_windows():
        return
    try:
        import ctypes
        from ctypes import wintypes

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020

        user32 = ctypes.windll.user32

        GetWindowLongW = user32.GetWindowLongW
        GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        GetWindowLongW.restype = ctypes.c_long

        SetWindowLongW = user32.SetWindowLongW
        SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        SetWindowLongW.restype = ctypes.c_long

        ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED  # keep layered for transparency keying

        if enable:
            ex |= WS_EX_TRANSPARENT
        else:
            ex &= ~WS_EX_TRANSPARENT

        SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    except Exception:
        # If anything goes wrong, just silently keep normal interaction.
        return

# ----------------------------
# Overlay UI
# ----------------------------

class OverlayApp:
    def __init__(self, schedule_path: str):
        self.items = load_schedule(schedule_path)

        self.root = tk.Tk()
        self.root.title("Overlay Countdown")

        self.transparent_color = "#ff00ff"  # magenta key
        self.root.configure(bg=self.transparent_color)

        # Borderless + always on top
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # True background-key transparency on Windows
        self._enable_transparency_key()

        # Variables / labels
        self.title_var = tk.StringVar(value="")
        self.time_var = tk.StringVar(value="")

        self.title_lbl = tk.Label(
            self.root,
            textvariable=self.title_var,
            fg="white",
            bg=self.transparent_color,
            font=("Segoe UI", 18, "bold"),
            padx=10, pady=2
        )
        self.title_lbl.pack()

        self.time_lbl = tk.Label(
            self.root,
            textvariable=self.time_var,
            fg="white",
            bg=self.transparent_color,
            font=("Consolas", 34, "bold"),
            padx=10, pady=0
        )
        self.time_lbl.pack()

        # Menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)

        # Drag state
        self._dragging = False
        self._drag_off_x = 0
        self._drag_off_y = 0

        # Place initially
        self._place_top_right(margin_x=20, margin_y=20)

        # Make click-through by default (Windows)
        self.root.update_idletasks()
        self.hwnd = self.root.winfo_id()
        _try_enable_clickthrough(self.hwnd, enable=True)

        # Key state tracking for CTRL+SHIFT
        self.ctrl_down = False
        self.shift_down = False

        # Bind key events (use bind_all so it works even if not focused)
        self.root.bind_all("<KeyPress-Control_L>", self._on_ctrl_down)
        self.root.bind_all("<KeyRelease-Control_L>", self._on_ctrl_up)
        self.root.bind_all("<KeyPress-Control_R>", self._on_ctrl_down)
        self.root.bind_all("<KeyRelease-Control_R>", self._on_ctrl_up)

        self.root.bind_all("<KeyPress-Shift_L>", self._on_shift_down)
        self.root.bind_all("<KeyRelease-Shift_L>", self._on_shift_up)
        self.root.bind_all("<KeyPress-Shift_R>", self._on_shift_down)
        self.root.bind_all("<KeyRelease-Shift_R>", self._on_shift_up)

        # Mouse bindings on the root window
        self.root.bind("<ButtonPress-1>", self._on_left_down)
        self.root.bind("<B1-Motion>", self._on_left_drag)
        self.root.bind("<ButtonRelease-1>", self._on_left_up)

        self.root.bind("<ButtonPress-3>", self._on_right_down)

        # Escape as backup close
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self._tick()

    def _enable_transparency_key(self):
        try:
            self.root.wm_attributes("-transparentcolor", self.transparent_color)
        except tk.TclError:
            # Should be supported on Windows; fallback anyway
            self.root.attributes("-alpha", 0.90)

    def _place_top_right(self, margin_x: int, margin_y: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        x = max(0, sw - w - margin_x)
        y = margin_y
        self.root.geometry(f"+{x}+{y}")

    def _ctrl_shift_active(self) -> bool:
        return self.ctrl_down and self.shift_down

    def _update_clickthrough(self):
        # If CTRL+SHIFT held, disable click-through so we can drag / right-click.
        _try_enable_clickthrough(self.hwnd, enable=not self._ctrl_shift_active())

    # ---- key handlers ----
    def _on_ctrl_down(self, _e):
        self.ctrl_down = True
        self._update_clickthrough()

    def _on_ctrl_up(self, _e):
        self.ctrl_down = False
        self._update_clickthrough()

    def _on_shift_down(self, _e):
        self.shift_down = True
        self._update_clickthrough()

    def _on_shift_up(self, _e):
        self.shift_down = False
        self._update_clickthrough()

    # ---- mouse handlers ----
    def _on_left_down(self, e):
        if not self._ctrl_shift_active():
            return
        self._dragging = True
        # store offset inside window
        self._drag_off_x = e.x
        self._drag_off_y = e.y

    def _on_left_drag(self, e):
        if not self._dragging:
            return
        # move window so cursor keeps same relative offset
        x = self.root.winfo_pointerx() - self._drag_off_x
        y = self.root.winfo_pointery() - self._drag_off_y
        self.root.geometry(f"+{x}+{y}")

    def _on_left_up(self, _e):
        self._dragging = False

    def _on_right_down(self, e):
        if not self._ctrl_shift_active():
            return
        try:
            self.menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            self.menu.grab_release()

    # ---- main timer update ----
    def _tick(self):
        now = datetime.now()
        title, timer = compute_display(self.items, now)

        self.title_var.set(title)
        self.time_var.set("" if timer is None else timer)

        # Don't auto-reposition once user has moved it.
        # (If you DO want it to keep snapping to top-right, remove this flag.)
        # We’ll detect "user moved" by whether they've ever dragged it.
        # If you prefer always snapping, uncomment next line:
        # self._place_top_right(margin_x=20, margin_y=20)

        self.root.after(200, self._tick)

    def run(self):
        self.root.mainloop()

def default_schedule_path() -> str:
    # Same folder as the script file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "Bell-Schedule.txt")

def main():
    schedule_path = sys.argv[1] if len(sys.argv) > 1 else default_schedule_path()

    if not os.path.exists(schedule_path):
        print(f"Schedule file not found: {schedule_path}")
        print("Usage: python overlay_timer.py path\\to\\schedule.csv")
        print("Default expected next to script:", schedule_path)
        sys.exit(1)

    app = OverlayApp(schedule_path)
    app.run()

if __name__ == "__main__":
    main()
