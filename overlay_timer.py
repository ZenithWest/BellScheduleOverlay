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
    t1: time
    t2: Optional[time]

def parse_hhmm(s: str) -> time:
    s = s.strip()
    hh, mm = s.split(":")
    return time(hour=int(hh), minute=int(mm))

def load_schedule(path: str) -> List[Item]:
    items: List[Item] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2:
                title, t = parts
                items.append(Item(title, parse_hhmm(t), None))
            elif len(parts) >= 3:
                title, t1, t2 = parts[0], parts[1], parts[2]
                items.append(Item(title, parse_hhmm(t1), parse_hhmm(t2)))
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
    return items[idx + 1].t1 if idx + 1 < len(items) else None

def fmt_hhmmss(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:d}:{m:02d}:{s:02d}"

def compute_display(items: List[Item], now: datetime) -> Tuple[str, Optional[str]]:
    for i, item in enumerate(items):
        begin = dt_today(item.t1)
        end = dt_today(item.t2) if item.t2 else None

        if end is None:
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)
            nxt = next_begin_of(items, i)
            if nxt is not None:
                nxt_dt = dt_today(nxt)
                if begin <= now < nxt_dt:
                    return f"Transitioning from {item.title} to {items[i+1].title}", None
        else:
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)
            if begin <= now < end:
                return item.title, fmt_hhmmss(end - now)
            nxt = next_begin_of(items, i)
            if nxt is not None:
                nxt_dt = dt_today(nxt)
                if end <= now < nxt_dt:
                    return f"Transitioning from {item.title} to {items[i+1].title}", None

    last_dt = dt_today(last_time_of(items[-1]))
    if now >= last_dt:
        return "End of School", fmt_hhmmss(now - last_dt)

    return "Schedule", None

# ----------------------------
# Windows helpers
# ----------------------------

def is_windows() -> bool:
    return platform.system().lower() == "windows"

def set_clickthrough(hwnd: int, enable: bool) -> None:
    """enable=True => mouse clicks pass through; False => window receives mouse."""
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
        SetWindowLongW = user32.SetWindowLongW
        GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        GetWindowLongW.restype = ctypes.c_long
        SetWindowLongW.restype = ctypes.c_long

        ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED
        if enable:
            ex |= WS_EX_TRANSPARENT
        else:
            ex &= ~WS_EX_TRANSPARENT
        SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    except Exception:
        pass

def ctrl_shift_down_global() -> bool:
    """Detect CTRL+SHIFT globally (works even if overlay is not focused)."""
    if not is_windows():
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_CONTROL = 0x11
        VK_SHIFT = 0x10
        # high bit set when key is down
        ctrl = (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
        shift = (user32.GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0
        return ctrl and shift
    except Exception:
        return False

# ----------------------------
# Overlay UI
# ----------------------------

class OverlayApp:
    def __init__(self, schedule_path: str):
        self.items = load_schedule(schedule_path)

        self.root = tk.Tk()
        self.root.title("Overlay Countdown")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Color key for transparency (choose something very unlikely)
        self.key_color = self.transparent_color = "#ff00ff"
        self.root.configure(bg=self.key_color)

        self.title_var = tk.StringVar(value="")
        self.time_var = tk.StringVar(value="")

        self.title_lbl = tk.Label(
            self.root,
            textvariable=self.title_var,
            fg="white",
            bg=self.key_color,
            font=("Segoe UI", 18, "bold"),
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=2
        )
        self.title_lbl.pack(fill="both")  # fill prevents "cyan sliver" gaps

        self.time_lbl = tk.Label(
            self.root,
            textvariable=self.time_var,
            fg="white",
            bg=self.key_color,
            font=("Consolas", 34, "bold"),
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=0
        )
        self.time_lbl.pack(fill="both")

        # Context menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)

        # Drag state
        self._dragging = False
        self._drag_off_x = 0
        self._drag_off_y = 0

        # Mouse bindings (work when click-through is disabled)
        self.root.bind("<ButtonPress-1>", self._on_left_down)
        self.root.bind("<B1-Motion>", self._on_left_drag)
        self.root.bind("<ButtonRelease-1>", self._on_left_up)
        self.root.bind("<ButtonPress-3>", self._on_right_down)

        # Backup close
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        # Initial placement
        self._place_top_right(20, 20)

        # IMPORTANT: realize window, then apply transparentcolor
        self.root.update()  # ensure HWND exists and window is mapped

        # Apply transparency key (try both attribute spellings)
        applied = False
        for fn in (self.root.wm_attributes, self.root.attributes):
            try:
                fn("-transparentcolor", self.key_color)
                applied = True
                break
            except tk.TclError:
                continue

        if not applied:
            # Fallback: whole-window translucency (not ideal, but avoids black box)
            try:
                self.root.attributes("-alpha", 0.92)
            except tk.TclError:
                pass

        self.hwnd = self.root.winfo_id()
        self._clickthrough_enabled = None  # unknown initially

        # Start ticking
        self._tick()

    def _place_top_right(self, mx: int, my: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_reqwidth()
        x = max(0, sw - w - mx)
        y = my
        self.root.geometry(f"+{x}+{y}")

    def _set_clickthrough_if_needed(self, enable: bool):
        if self._clickthrough_enabled is enable:
            return
        set_clickthrough(self.hwnd, enable=enable)
        self._clickthrough_enabled = enable

    # Mouse handlers
    def _on_left_down(self, e):
        # Only allow drag while CTRL+SHIFT is held (we disable click-through during that)
        if not ctrl_shift_down_global():
            return
        self._dragging = True
        self._drag_off_x = e.x
        self._drag_off_y = e.y

    def _on_left_drag(self, _e):
        if not self._dragging:
            return
        x = self.root.winfo_pointerx() - self._drag_off_x
        y = self.root.winfo_pointery() - self._drag_off_y
        self.root.geometry(f"+{x}+{y}")

    def _on_left_up(self, _e):
        self._dragging = False

    def _on_right_down(self, _e):
        if not ctrl_shift_down_global():
            return
        try:
            self.menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            self.menu.grab_release()

    def _tick(self):
        # Global CTRL+SHIFT toggles click-through:
        # - held => interactive (can drag / menu)
        # - not held => click-through
        interactive = ctrl_shift_down_global()
        self._set_clickthrough_if_needed(enable=not interactive)

        now = datetime.now()
        title, timer = compute_display(self.items, now)
        self.title_var.set(title)
        self.time_var.set("" if timer is None else timer)

        self.root.after(200, self._tick)

    def run(self):
        self.root.mainloop()

def default_schedule_path() -> str:
    # Same folder as the script (Windows path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "Bell-Schedule.txt")

def main():
    schedule_path = sys.argv[1] if len(sys.argv) > 1 else default_schedule_path()
    if not os.path.exists(schedule_path):
        print(f"Schedule file not found: {schedule_path}")
        print("Put Bell-Schedule.txt next to overlay_timer.py (or pass a path as argv[1]).")
        sys.exit(1)

    OverlayApp(schedule_path).run()

if __name__ == "__main__":
    main()
