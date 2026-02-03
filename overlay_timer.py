import sys
import os
import platform
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple
import tkinter.font as tkfont

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
            # single-time item
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)

            nxt = next_begin_of(items, i)
            if nxt is not None:
                nxt_dt = dt_today(nxt)
                if begin <= now < nxt_dt:
                    return (
                        f"Transitioning from {item.title} to {items[i+1].title}",
                        fmt_hhmmss(nxt_dt - now),
                    )

        else:
            # two-time item
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)

            if begin <= now < end:
                return item.title, fmt_hhmmss(end - now)

            nxt = next_begin_of(items, i)
            if nxt is not None:
                nxt_dt = dt_today(nxt)
                if end <= now < nxt_dt:
                    return (
                        f"Transitioning from {item.title} to {items[i+1].title}",
                        fmt_hhmmss(nxt_dt - now),
                    )

    # Past the last time of the last item => show elapsed
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

        # Transparency key (kept permanently enabled)
        self.key_color = "#ff00ff"
        self.root.configure(bg=self.key_color)

        # --- scalable style (base values at scale=1.0) ---
        self.scale = 1.0
        self.min_scale = 0.60
        self.max_scale = 3.00

        self.base_title_size = 18
        self.base_time_size = 34
        self.base_padx = 10
        self.base_title_pady = 2
        self.base_time_pady = 0

        self.resize_margin = 12  # px region near edges used for resizing (grab mode only)

        # Use Tk Font objects so we can resize cleanly
        self.title_font = tkfont.Font(family="Segoe UI", size=self.base_title_size, weight="bold")
        self.time_font = tkfont.Font(family="Consolas", size=self.base_time_size, weight="bold")

        self.title_var = tk.StringVar(value="Loading…")
        self.time_var = tk.StringVar(value="0:00:00")

        self.title_lbl = tk.Label(
            self.root, textvariable=self.title_var,
            fg="white", bg=self.key_color,
            font=self.title_font,
            bd=0, highlightthickness=0
        )
        self.title_lbl.pack(fill="both")

        self.time_lbl = tk.Label(
            self.root, textvariable=self.time_var,
            fg="white", bg=self.key_color,
            font=self.time_font,
            bd=0, highlightthickness=0
        )
        self.time_lbl.pack(fill="both")

        # Context menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)

        # Drag/resize state
        self._mode = None          # None / "move" / "resize"
        self._resize_dir = None    # e.g. "l", "r", "b", "t", "rb", etc.
        self._drag_off_x = 0
        self._drag_off_y = 0

        self._start_mouse_x = 0
        self._start_mouse_y = 0
        self._start_x = 0
        self._start_y = 0
        self._start_w = 0
        self._start_h = 0
        self._start_scale = 1.0
        self._aspect = 1.0

        # Visual mode
        self._grab_mode = False

        # Mouse bindings (only receive clicks when CTRL+SHIFT is down due to HTTRANSPARENT)
        self.root.bind("<ButtonPress-1>", self._on_left_down)
        self.root.bind("<B1-Motion>", self._on_left_drag)
        self.root.bind("<ButtonRelease-1>", self._on_left_up)
        self.root.bind("<ButtonPress-3>", self._on_right_down)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        # Cursor feedback while in grab mode (CTRL+SHIFT held)
        for w in (self.root, self.title_lbl, self.time_lbl):
            w.bind("<Motion>", self._on_motion_update_cursor)
            w.bind("<Leave>", self._on_leave_reset_cursor)


        # Place & realize
        self._place_top_right(20, 20)
        self.root.update()

        # Apply transparency key
        self.root.wm_attributes("-transparentcolor", self.key_color)

        # Install click-through-by-hit-test (no WS_EX_TRANSPARENT)
        self.hwnd = self.root.winfo_id()
        self._hit_test = WinClickThroughByHitTest(self.hwnd)

        # Apply initial style scaling (sets paddings)
        self._apply_scale(self.scale)

        self._tick()

    # ----------------------------
    # Scaling + grab mode visuals
    # ----------------------------

    def _apply_scale(self, scale: float):
        """Apply proportional scaling to fonts and paddings (no stretching)."""
        scale = max(self.min_scale, min(self.max_scale, scale))
        self.scale = scale

        title_size = max(8, int(round(self.base_title_size * scale)))
        time_size = max(10, int(round(self.base_time_size * scale)))

        padx = int(round(self.base_padx * scale))
        title_pady = int(round(self.base_title_pady * scale))
        time_pady = int(round(self.base_time_pady * scale))

        self.title_font.configure(size=title_size)
        self.time_font.configure(size=time_size)

        self.title_lbl.configure(padx=padx, pady=title_pady)
        self.time_lbl.configure(padx=padx, pady=time_pady)

        # Update layout so requested size updates immediately
        self.root.update_idletasks()

    def _set_grab_mode(self, grab: bool):
        """
        grab=False => transparent background (magenta key)
        grab=True  => opaque black background to make resizing/dragging easier
        """
        if self._grab_mode == grab:
            return
        self._grab_mode = grab

        bg = "black" if grab else self.key_color
        self.root.configure(bg=bg)
        self.title_lbl.configure(bg=bg)
        self.time_lbl.configure(bg=bg)

        if grab:
            self._set_cursor("fleur")
        else:
            self._set_cursor("")


    # ----------------------------
    # Position helpers
    # ----------------------------

    def _place_top_right(self, mx: int, my: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_reqwidth()
        x = max(0, sw - w - mx)
        y = my
        self.root.geometry(f"+{x}+{y}")

    def _window_geom(self):
        """Return (x, y, w, h) current."""
        self.root.update_idletasks()
        return (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())

    def _hit_region(self, w: int, h: int, px: int, py: int) -> Optional[str]:
        """
        Determine resize direction based on pointer inside window client area.
        Returns one of: l,r,t,b,lt,rt,lb,rb or None if not in resize margin.
        """
        m = self.resize_margin
        left = px <= m
        right = px >= w - m
        top = py <= m
        bottom = py >= h - m

        if top and left: return "lt"
        if top and right: return "rt"
        if bottom and left: return "lb"
        if bottom and right: return "rb"
        if left: return "l"
        if right: return "r"
        if top: return "t"
        if bottom: return "b"
        return None

    # ----------------------------
    # Mouse handlers (CTRL+SHIFT held)
    # ----------------------------

    def _on_left_down(self, e):
        if not ctrl_shift_down_global():
            return

        x, y, w, h = self._window_geom()
        self._start_x, self._start_y, self._start_w, self._start_h = x, y, w, h
        self._start_mouse_x = self.root.winfo_pointerx()
        self._start_mouse_y = self.root.winfo_pointery()
        self._start_scale = self.scale
        self._aspect = (w / h) if h else 1.0

        # Choose resize vs move
        # Only allow resizing when in grab mode (black background), which is when CTRL+SHIFT is held
        px, py = self._pointer_in_root()
        region = self._hit_region(w, h, px, py)

        if region:
            self._mode = "resize"
            self._resize_dir = region
        else:
            self._mode = "move"
            self._resize_dir = None
            # store offset from window top-left in screen coords
            self._drag_off_x = self.root.winfo_pointerx() - x
            self._drag_off_y = self.root.winfo_pointery() - y

    def _on_left_drag(self, _e):
        if not ctrl_shift_down_global():
            # If user releases keys mid-drag, stop the gesture
            self._mode = None
            self._resize_dir = None
            return

        if self._mode == "move":
            x = self.root.winfo_pointerx() - self._drag_off_x
            y = self.root.winfo_pointery() - self._drag_off_y
            self.root.geometry(f"+{x}+{y}")
            return

        if self._mode != "resize" or not self._resize_dir:
            return

        # Compute mouse delta in screen coords
        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        dx = mx - self._start_mouse_x
        dy = my - self._start_mouse_y

        # Start from initial geometry
        x0, y0, w0, h0 = self._start_x, self._start_y, self._start_w, self._start_h
        aspect = self._aspect

        # Propose new w/h based on which edge is being dragged
        # Then convert to a uniform scale to preserve aspect ratio.
        # For corners: use the larger relative change to feel natural.
        proposed_w = w0
        proposed_h = h0

        dir_ = self._resize_dir

        if "r" in dir_:
            proposed_w = w0 + dx
        if "l" in dir_:
            proposed_w = w0 - dx
        if "b" in dir_:
            proposed_h = h0 + dy
        if "t" in dir_:
            proposed_h = h0 - dy

        # Derive uniform scale
        # If only width edge: scale from width. If only height edge: scale from height.
        # If corner: pick whichever movement implies larger scale change.
        scale_w = proposed_w / w0 if w0 else 1.0
        scale_h = proposed_h / h0 if h0 else 1.0

        if dir_ in ("l", "r"):
            s = scale_w
        elif dir_ in ("t", "b"):
            s = scale_h
        else:
            # corner
            s = scale_w if abs(scale_w - 1.0) >= abs(scale_h - 1.0) else scale_h

        # Apply clamp in terms of overall scale (relative to current global scale)
        new_scale = self._start_scale * s
        new_scale = max(self.min_scale, min(self.max_scale, new_scale))

        # Convert back into w/h based on starting w/h and the *actual* scale ratio we applied
        applied_ratio = new_scale / self._start_scale if self._start_scale else 1.0
        w = int(round(w0 * applied_ratio))
        h = int(round(h0 * applied_ratio))

        # Preserve aspect exactly (avoid drift)
        # Force h from w/aspect (or w from h*aspect depending on stability)
        if aspect > 0:
            h = int(round(w / aspect))

        # Clamp absolute min/max as a second guard (optional)
        # You can tune these if you prefer hard bounds in pixels
        min_w, min_h = 220, 90
        max_w, max_h = 1200, 600
        if w < min_w:
            w = min_w
            h = int(round(w / aspect))
        if h < min_h:
            h = min_h
            w = int(round(h * aspect))
        if w > max_w:
            w = max_w
            h = int(round(w / aspect))
        if h > max_h:
            h = max_h
            w = int(round(h * aspect))

        # Adjust x/y if resizing from left/top so the opposite edge stays anchored
        x = x0
        y = y0
        if "l" in dir_:
            x = x0 + (w0 - w)
        if "t" in dir_:
            y = y0 + (h0 - h)

        # Apply scale to fonts/padding first, then force window size.
        self._apply_scale(new_scale)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _on_left_up(self, _e):
        self._mode = None
        self._resize_dir = None

    def _on_right_down(self, _e):
        if not ctrl_shift_down_global():
            return
        try:
            self.menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            self.menu.grab_release()

    # ----------------------------
    # Mouse Symbols
    # ----------------------------

    def _set_cursor(self, cursor: str):
        """Set cursor on root + labels so it works over the whole box."""
        self.root.configure(cursor=cursor)
        self.title_lbl.configure(cursor=cursor)
        self.time_lbl.configure(cursor=cursor)

    def _cursor_for_region(self, region: Optional[str]) -> str:
        """
        Map our resize region to Tk cursor names.
        Return '' for default cursor.
        """
        if region is None:
            return "fleur"  # move cursor (pan) when inside box

        # Corners
        if region in ("lt", "rb"):
            return "size_nw_se"
        if region in ("rt", "lb"):
            return "size_ne_sw"

        # Edges
        if region in ("l", "r"):
            return "size_we"
        if region in ("t", "b"):
            return "size_ns"

        return "fleur"

    def _on_motion_update_cursor(self, e):
        # Only show special cursors while CTRL+SHIFT is held
        if not ctrl_shift_down_global():
            self._set_cursor("")
            return

        # Determine which region the pointer is in relative to the window
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        px, py = self._pointer_in_root()

        region = self._hit_region(w, h, px, py)
        self._set_cursor(self._cursor_for_region(region))

    def _on_leave_reset_cursor(self, _e):
        # When leaving the box, restore default unless still in grab mode
        if not ctrl_shift_down_global():
            self._set_cursor("")

    def _pointer_in_root(self) -> tuple[int, int]:
        """Pointer position in *root window* coordinates (0..w, 0..h)."""
        px = self.root.winfo_pointerx() - self.root.winfo_rootx()
        py = self.root.winfo_pointery() - self.root.winfo_rooty()
        return px, py


    # ----------------------------
    # Main update loop
    # ----------------------------

    def _tick(self):
        # CTRL+SHIFT => grab mode (black background); otherwise transparent
        grab = ctrl_shift_down_global()
        self._set_grab_mode(grab)

        now = datetime.now()
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
