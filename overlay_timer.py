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
# Windows: global CTRL+SHIFT + WM_NCHITTEST click-through
# ----------------------------

def is_windows() -> bool:
    return platform.system().lower() == "windows"

def ctrl_shift_down_global() -> bool:
    if not is_windows():
        return False
    import ctypes
    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    ctrl = (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
    shift = (user32.GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0
    return ctrl and shift

class WinClickThroughByHitTest:
    """
    Subclasses the Tk window proc.
    When CTRL+SHIFT is NOT held -> return HTTRANSPARENT on WM_NCHITTEST (click-through).
    When CTRL+SHIFT IS held -> behave normally (interactive).
    """
    def __init__(self, hwnd: int):
        if not is_windows():
            return

        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32

        self.WM_NCHITTEST = 0x0084
        self.HTTRANSPARENT = -1

        # Use SetWindowLongPtrW on 64-bit, SetWindowLongW on 32-bit
        self.GWLP_WNDPROC = -4

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
                                     wintypes.HWND,
                                     wintypes.UINT,
                                     wintypes.WPARAM,
                                     wintypes.LPARAM)

        # Get original WndProc
        GetWindowLongPtrW = getattr(self.user32, "GetWindowLongPtrW", None)
        SetWindowLongPtrW = getattr(self.user32, "SetWindowLongPtrW", None)

        if GetWindowLongPtrW and SetWindowLongPtrW:
            GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            GetWindowLongPtrW.restype = ctypes.c_void_p
            SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            SetWindowLongPtrW.restype = ctypes.c_void_p

            self._orig = GetWindowLongPtrW(hwnd, self.GWLP_WNDPROC)
            self._orig_wndproc = WNDPROC(self._orig)
            self._new_wndproc = WNDPROC(self._proc)

            SetWindowLongPtrW(hwnd, self.GWLP_WNDPROC, ctypes.cast(self._new_wndproc, ctypes.c_void_p))
        else:
            # 32-bit fallback (rare nowadays)
            GetWindowLongW = self.user32.GetWindowLongW
            SetWindowLongW = self.user32.SetWindowLongW
            GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            GetWindowLongW.restype = ctypes.c_long
            SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            SetWindowLongW.restype = ctypes.c_long

            self._orig = GetWindowLongW(hwnd, self.GWLP_WNDPROC)
            self._orig_wndproc = WNDPROC(self._orig)
            self._new_wndproc = WNDPROC(self._proc)
            SetWindowLongW(hwnd, self.GWLP_WNDPROC, ctypes.cast(self._new_wndproc, ctypes.c_long))

        # Keep references so GC doesn't collect callback
        self._hwnd = hwnd

    def _proc(self, hwnd, msg, wparam, lparam):
        # If not holding CTRL+SHIFT, make mouse hit-test transparent
        if msg == self.WM_NCHITTEST and not ctrl_shift_down_global():
            return self.HTTRANSPARENT
        return self._orig_wndproc(hwnd, msg, wparam, lparam)

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

        # Track current visual mode so we only update when it changes
        self._grab_mode = False  # False = transparent mode, True = black background mode

        # Use known-good magenta key for transparency
        self.key_color = "#ff00ff"
        self.root.configure(bg=self.key_color)

        self.title_var = tk.StringVar(value="Loading…")
        self.time_var = tk.StringVar(value="0:00:00")

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
        self.title_lbl.pack(fill="both")

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

        # Menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)

        # Drag state
        self._dragging = False
        self._drag_off_x = 0
        self._drag_off_y = 0

        # Mouse bindings (only “work” when CTRL+SHIFT is held, because otherwise hit-test is transparent)
        self.root.bind("<ButtonPress-1>", self._on_left_down)
        self.root.bind("<B1-Motion>", self._on_left_drag)
        self.root.bind("<ButtonRelease-1>", self._on_left_up)
        self.root.bind("<ButtonPress-3>", self._on_right_down)

        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self._place_top_right(20, 20)

        # Realize window then apply transparentcolor
        self.root.update()

        # Apply Tk color-key transparency
        self.root.wm_attributes("-transparentcolor", self.key_color)

        # Install hit-test click-through (no WS_EX_TRANSPARENT!)
        self.hwnd = self.root.winfo_id()
        self._hit_test = WinClickThroughByHitTest(self.hwnd)

        # Start ticking
        self._tick()

    def _set_grab_mode(self, grab: bool):
        """
        grab=False => transparent background (magenta key color)
        grab=True  => opaque black background (easier to drag)
        """
        if self._grab_mode == grab:
            return
        self._grab_mode = grab

        bg = "black" if grab else self.key_color

        # Window + labels backgrounds
        self.root.configure(bg=bg)
        self.title_lbl.configure(bg=bg)
        self.time_lbl.configure(bg=bg)

        # Optional: add a little padding/outline feel in grab mode
        # (Uncomment if you want it slightly larger/easier to grab)
        # self.title_lbl.configure(padx=14 if grab else 10, pady=6 if grab else 2)
        # self.time_lbl.configure(padx=14 if grab else 10, pady=4 if grab else 0)

    def _place_top_right(self, mx: int, my: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_reqwidth()
        x = max(0, sw - w - mx)
        y = my
        self.root.geometry(f"+{x}+{y}")

    def _on_left_down(self, e):
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
        now = datetime.now()

        grab = ctrl_shift_down_global()  # CTRL+SHIFT held?
        self._set_grab_mode(grab)

        title, timer = compute_display(self.items, now)
        self.title_var.set(title)
        self.time_var.set("" if timer is None else timer)

        self.root.after(200, self._tick)

    def run(self):
        self.root.mainloop()

def default_schedule_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "Bell-Schedule.txt")

def main():
    schedule_path = sys.argv[1] if len(sys.argv) > 1 else default_schedule_path()
    if not os.path.exists(schedule_path):
        print(f"Schedule file not found: {schedule_path}")
        print("Put Bell-Schedule.txt next to overlay_timer.py or pass its path as argv[1].")
        sys.exit(1)

    OverlayApp(schedule_path).run()

if __name__ == "__main__":
    main()
