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
                return item.title, None, fmt_hhmmss(begin - now)

            nxt = next_begin_of(items, i)
            if nxt is not None:
                nxt_dt = dt_today(nxt)
                if begin <= now < nxt_dt:
                    return ("Transitioning", f"{item.title} → {items[i+1].title}", fmt_hhmmss(nxt_dt - now))

        else:
            # two-time item
            if now < begin:
                return item.title, None, fmt_hhmmss(begin - now)

            if begin <= now < end:
                return item.title, None, fmt_hhmmss(end - now)

            nxt = next_begin_of(items, i)
            if nxt is not None:
                nxt_dt = dt_today(nxt)
                if end <= now < nxt_dt:
                    return ("Transitioning", f"{item.title} → {items[i+1].title}", fmt_hhmmss(nxt_dt - now))

    # Past the last time of the last item => show elapsed
    last_dt = dt_today(last_time_of(items[-1]))
    if now >= last_dt:
        return "End of School", None, fmt_hhmmss(now - last_dt)

    return "Schedule", None, None


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


def force_taskbar_icon(hwnd: int):
    """Force a borderless Tk window to show in the Windows taskbar."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080

    GetWindowLongW = user32.GetWindowLongW
    SetWindowLongW = user32.SetWindowLongW
    GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    GetWindowLongW.restype = ctypes.c_long
    SetWindowLongW.restype = ctypes.c_long

    exstyle = GetWindowLongW(hwnd, GWL_EXSTYLE)
    exstyle = (exstyle | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

    # Nudge Windows to refresh the taskbar representation
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                       0x0001 | 0x0002 | 0x0020)  # SWP_NOSIZE|SWP_NOMOVE|SWP_FRAMECHANGED


# ----------------------------
# Overlay UI
# ----------------------------

class OverlayApp:
    def __init__(self, schedule_path: str):
        self.items = load_schedule(schedule_path)

        self.root = tk.Tk()
        self.root.title("Bell Schedule Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bell.ico")
        if os.path.exists(ico_path):
            self.root.iconbitmap(ico_path)

        # Transparency key - slightly off magenta (kept permanently enabled)
        self.key_color = "#ff01ff"
        self.root.configure(bg=self.key_color)

        # --- scalable style (base values at scale=1.0) ---
        self.scale = 1.0
        self.min_scale = 0.60
        self.max_scale = 10.00

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


        self.gap_frame = tk.Frame(self.root, bg=self.key_color, height=0, bd=0, highlightthickness=0)
        self.gap_frame.pack(fill="x")
        self.gap_frame.pack_propagate(False)  # keep exact height (don't shrink to contents)

        self.time_lbl = tk.Label(
            self.root, textvariable=self.time_var,
            fg="white", bg=self.key_color,
            font=self.time_font,
            bd=0, highlightthickness=0
        )
        self.time_lbl.pack(fill="both")
        self._last_title = ""
        self._last_time = ""

        # Subtitle (used for "A → B" during transitions)
        self.sub_var = tk.StringVar(value="")
        self.sub_font_base_size = 12     # your normal subtitle size at scale=1
        self.sub_ratio = 0.75            # scales smaller than title
        self.sub_min_size = 7
        self._sub_size_current = None    # will track last applied size (for stability)


        self.sub_font = tkfont.Font(family="Segoe UI", size=self.sub_font_base_size, weight="bold")

        self.sub_lbl = tk.Label(
            self.root,
            textvariable=self.sub_var,
            fg=self.title_lbl.cget("fg"),     # same color as title by default
            bg=self.key_color,
            font=self.sub_font,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=0,
            anchor="center",     # ← important
            justify="center"
        )


        # Help text shown only in grab mode (CTRL+SHIFT)
        self.help_var = tk.StringVar(value="CTRL+SHIFT+RightClick for Menu!")
        self.base_help_size = 11          # at scale=1.0
        self.help_ratio = 0.65            # helper = 65% of normal scaling
        self.help_min_size = 7
        self.help_font = tkfont.Font(
            family="Segoe UI",
            size=self.base_help_size,
            weight="bold"
        )
        self.help_lbl = tk.Label(
            self.root,
            textvariable=self.help_var,
            fg="yellow",
            bg=self.key_color,
            font=self.help_font,
            bd=0,
            highlightthickness=0,
            padx=6,
            pady=2
        )
        self._last_timer_text = ""
        self._last_scale_for_help = self.scale
        self._current_cursor = ""
        # DO NOT pack yet — we control visibility dynamically


        # Context menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.color_menu = tk.Menu(self.menu, tearoff=0)

        colors = [
            ("White", "white"),
            ("Black", "black"),
            ("Yellow", "yellow"),
            ("Magenta", "magenta"),
            ("Green", "#7CFF00"),
            ("Blue", "blue"),
            ("Red", "red"),
        ]


        for label, value in colors:
            self.color_menu.add_command(label=label, command=lambda v=value: self._set_text_color(v))

        self.menu.add_cascade(label="Color", menu=self.color_menu)
        self.menu.add_separator()
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
        self.grab_bg = "#000000"   # black
        self.grab_alpha = 0.5     # 50% opacity

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

        if platform.system().lower() == "windows":
            force_taskbar_icon(self.hwnd)

        self._tick()

    # ----------------------------
    # Scaling + grab mode visuals
    # ----------------------------

    def _apply_scale(self, scale: float):
        """Apply proportional scaling to fonts and paddings (no stretching)."""
        scale = max(self.min_scale, min(self.max_scale, scale))
        self.scale = scale

        title_size = max(8, int(round(self.base_title_size * scale)))
        time_size  = max(10, int(round(self.base_time_size * scale)))

        sub_size = int(round(self.sub_font_base_size * scale * self.sub_ratio))
        sub_size = max(self.sub_min_size, sub_size)
        self.sub_font.configure(size=sub_size)

        # Helper scales with the overlay but stays smaller
        help_size = int(round(self.base_help_size * scale * self.help_ratio))
        help_size = max(self.help_min_size, help_size)

        padx = int(round(self.base_padx * scale))
        title_pady = int(round(self.base_title_pady * scale))
        time_pady  = int(round(self.base_time_pady * scale))

        self.title_font.configure(size=title_size)
        self.time_font.configure(size=time_size)
        self.help_font.configure(size=help_size)

        self.title_lbl.configure(padx=padx, pady=title_pady)
        self.time_lbl.configure(padx=padx, pady=time_pady)

        # Update layout so requested size updates immediately
        self.root.update_idletasks()

    def _set_grab_mode(self, grab: bool):
        """
        grab=False => fully transparent overlay (color-key)
        grab=True  => semi-transparent background (alpha)
        """
        if self._grab_mode == grab:
            return
        self._grab_mode = grab

        if grab:
            # Switch to semi-transparent mode
            bg = self.grab_bg
            self.root.configure(bg=bg)
            self.title_lbl.configure(bg=bg)
            self.time_lbl.configure(bg=bg)
            self.help_lbl.configure(bg=bg)
            self.gap_frame.configure(bg=bg)
            self.sub_lbl.configure(bg=bg)

            # Disable color-key visually by not painting it
            # Apply alpha transparency
            self.root.attributes("-alpha", self.grab_alpha)

            self._set_cursor("fleur")

            # Show helper text
            self.help_lbl.pack(fill="x", pady=(2, 4))
            self._apply_scale(self.scale)          # ensures help font is correct instantly
            self._snap_to_content(anchor="topleft")

            #self._fit_help_text_to_timer()


        else:
            # Restore full transparency
            bg = self.key_color
            self.root.configure(bg=bg)
            self.title_lbl.configure(bg=bg)
            self.time_lbl.configure(bg=bg)
            self.help_lbl.configure(bg=bg)
            self.gap_frame.configure(bg=bg)
            self.sub_lbl.configure(bg=bg)

            # Restore full opacity
            self.root.attributes("-alpha", 1.0)

            # Hide helper text
            self.help_lbl.pack_forget()
            self._snap_to_content(anchor="topleft")

            self._set_cursor("")

    def _fit_help_text_to_timer(self):
        """
        Stable helper-text fitting:
        - Uses font.measure() (pixel-accurate, no geometry timing jitter)
        - Uses hysteresis to prevent rapid flip/flop
        - Only recalculates when needed
        """
        self.root.update_idletasks()

        help_text = self.help_var.get()
        timer_text = self.time_var.get()

        # If timer is blank (rare), don't change help size
        if not timer_text:
            return

        # Compute "target max width" = width of timer line (text + padding)
        # IMPORTANT: include the same horizontal padding the timer label uses
        timer_padx = int(self.time_lbl.cget("padx"))
        timer_target_px = self.time_font.measure(timer_text) + 2 * timer_padx

        # Helper padding
        help_padx = int(self.help_lbl.cget("padx"))

        # Base help size (scaled)
        base_size = max(7, int(round(self.help_font_base_size * self.scale)))

        # Current size
        cur_size = int(self.help_font.cget("size"))

        # We'll try to keep it as large as possible but never exceeding timer_target_px.
        # Hysteresis (deadband) in pixels:
        # - Only shrink if overflow > 2 px
        # - Only grow if we have at least 10 px spare (prevents flip-flop)
        SHRINK_EPS = 2
        GROW_EPS = 10

        def help_width_at(size: int) -> int:
            self.help_font.configure(size=size)
            return self.help_font.measure(help_text) + 2 * help_padx

        # Measure at current size
        cur_w = help_width_at(cur_size)

        # If too wide, shrink until it fits (with a small eps)
        if cur_w > timer_target_px + SHRINK_EPS:
            size = cur_size
            MIN_SIZE = 7
            while size > MIN_SIZE and help_width_at(size) > timer_target_px:
                size -= 1
            if size != cur_size:
                self.help_font.configure(size=size)
            return

        # If comfortably smaller, we can try to grow (up to base_size), but only if we have room
        if cur_size < base_size and cur_w < timer_target_px - GROW_EPS:
            size = cur_size
            while size < base_size and help_width_at(size + 1) <= timer_target_px:
                size += 1
            if size != cur_size:
                self.help_font.configure(size=size)
            return

        # Otherwise: stay put (prevents rapid flipping)
        self.help_font.configure(size=cur_size)

    def _fit_subtitle_to_gap(self, gap_px: int) -> int:
        """
        Returns a subtitle font size (int) that fits within gap_px vertically.
        Stable: only shrinks when needed; grows back slowly only when there's room.
        """
        # Start from the "desired" size at current scale
        desired = int(round(self.sub_font_base_size * self.scale * self.sub_ratio))
        desired = max(self.sub_min_size, desired)

        # Current size (cached)
        cur = self._sub_size_current
        if cur is None:
            cur = desired

        # How tall is current font?
        self.sub_font.configure(size=cur)
        cur_h = self.sub_font.metrics("linespace")

        # Deadbands (hysteresis) to prevent flip-flop
        SHRINK_EPS = 0   # shrink immediately if it doesn't fit
        GROW_EPS = 6     # only grow if we have at least 6px extra headroom

        # If it doesn't fit, shrink until it fits
        if cur_h > gap_px - SHRINK_EPS:
            s = cur
            while s > self.sub_min_size:
                s -= 1
                self.sub_font.configure(size=s)
                if self.sub_font.metrics("linespace") <= gap_px:
                    self._sub_size_current = s
                    return s
            self._sub_size_current = self.sub_min_size
            return self.sub_min_size

        # If it fits and we are below desired, maybe grow — but only if there's plenty of room
        if cur < desired:
            # check if we have enough headroom to try growing
            if (gap_px - cur_h) >= GROW_EPS:
                s = cur
                while s < desired:
                    next_s = s + 1
                    self.sub_font.configure(size=next_s)
                    if self.sub_font.metrics("linespace") <= gap_px:
                        s = next_s
                        continue
                    break
                self._sub_size_current = s
                self.sub_font.configure(size=s)
                return s

        # Otherwise keep current size
        self._sub_size_current = cur
        self.sub_font.configure(size=cur)
        return cur


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

    def _position_subtitle(self):
        """
        Float the subtitle centered horizontally and vertically
        between the Title and Timer, without affecting layout.
        """
        if not self.sub_lbl.winfo_ismapped():
            return

        self.root.update_idletasks()

        # Vertical placement (between title and timer)
        title_y = self.title_lbl.winfo_y()
        title_h = self.title_lbl.winfo_height()
        timer_y = self.time_lbl.winfo_y()

        gap_top = title_y + title_h
        gap_bottom = timer_y

        sub_h = self.sub_lbl.winfo_reqheight()

        if gap_bottom - gap_top < sub_h:
            y = gap_top - sub_h // 2
        else:
            y = gap_top + (gap_bottom - gap_top - sub_h) // 2

        # Horizontal centering (this is the key fix)
        win_w = self.root.winfo_width()
        sub_w = self.sub_lbl.winfo_reqwidth()

        x = (win_w - sub_w) // 2

        self.sub_lbl.place(in_=self.gap_frame, relx=0.5, rely=0.5, anchor="center")
        self.sub_lbl.lift()

    def _update_subtitle_layout(self, subtitle: str | None):
        if not subtitle:
            self.sub_lbl.place_forget()
            self.gap_frame.configure(height=0)
            self._sub_size_current = None
            return

        # Ensure the font size is correct for current scale (and shrink-to-fit-gap if you’re using it)
        # If you want gap-driven shrinking:
        # desired gap can be based on current subtitle font height.

        self.root.update_idletasks()

        sub_h = self.sub_font.metrics("linespace")
        target_gap = sub_h + 4  # breathing room

        self.gap_frame.configure(height=target_gap)
        self.root.update_idletasks()

        # Now show it centered in the gap frame (smooth)
        if not self.sub_lbl.winfo_ismapped():
            self.sub_lbl.place(in_=self.gap_frame, relx=0.5, rely=0.5, anchor="center")
            self.sub_lbl.lift()


    def _subtitle_pixel_size(self, text: str) -> tuple[int, int]:
        """
        Measure subtitle width/height in pixels without needing the widget mapped.
        """
        # width in pixels of the text
        w = self.sub_font.measure(text)

        # height in pixels of one line of text
        h = self.sub_font.metrics("linespace")

        # If you want a tiny vertical cushion, add a couple pixels:
        # h += 2

        return w, h



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
        # If user releases CTRL+SHIFT mid-drag, cancel the gesture.
        if not ctrl_shift_down_global():
            self._mode = None
            self._resize_dir = None
            self._dragging = False
            return

        # ----------------------------
        # MOVE
        # ----------------------------
        if self._mode == "move":
            x = self.root.winfo_pointerx() - self._drag_off_x
            y = self.root.winfo_pointery() - self._drag_off_y
            self.root.geometry(f"+{x}+{y}")
            return

        # ----------------------------
        # RESIZE (scale-only + snap)
        # ----------------------------
        if self._mode != "resize" or not self._resize_dir:
            return

        # Current mouse deltas (screen coords)
        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        dx = mx - self._start_mouse_x
        dy = my - self._start_mouse_y

        # Starting window geometry
        x0, y0, w0, h0 = self._start_x, self._start_y, self._start_w, self._start_h
        if w0 <= 0 or h0 <= 0:
            return

        # Keep edges anchored depending on direction
        right_edge = x0 + w0
        bottom_edge = y0 + h0

        # Propose new w/h based on drag direction
        proposed_w = w0
        proposed_h = h0

        d = self._resize_dir
        if "r" in d:
            proposed_w = w0 + dx
        if "l" in d:
            proposed_w = w0 - dx
        if "b" in d:
            proposed_h = h0 + dy
        if "t" in d:
            proposed_h = h0 - dy

        # Convert proposed change into a uniform scale factor.
        # - For left/right edges: scale from width
        # - For top/bottom edges: scale from height
        # - For corners: use whichever implies a larger magnitude change
        scale_w = proposed_w / w0
        scale_h = proposed_h / h0

        if d in ("l", "r"):
            s = scale_w
        elif d in ("t", "b"):
            s = scale_h
        else:
            # corner resize
            s = scale_w if abs(scale_w - 1.0) >= abs(scale_h - 1.0) else scale_h

        # Apply to starting scale and clamp
        new_scale = self._start_scale * s
        new_scale = max(self.min_scale, min(self.max_scale, new_scale))

        # Apply visual scaling (fonts/padding)
        self._apply_scale(new_scale)

        # Snap window size to content at this scale
        # (this is what prevents the giant black box issue)
        self._snap_to_content(anchor="topleft")

        # Re-anchor edges when resizing from left/top so it feels natural:
        # keep the "opposite edge" fixed.
        self.root.update_idletasks()
        new_w = self.root.winfo_width()
        new_h = self.root.winfo_height()
        new_x = self.root.winfo_x()
        new_y = self.root.winfo_y()

        if "l" in d:
            new_x = right_edge - new_w
        else:
            new_x = x0

        if "t" in d:
            new_y = bottom_edge - new_h
        else:
            new_y = y0

        self.root.geometry(f"+{new_x}+{new_y}")

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
        if cursor == self._current_cursor:
            return
        self._current_cursor = cursor
        self.root.configure(cursor=cursor)
        self.title_lbl.configure(cursor=cursor)
        self.time_lbl.configure(cursor=cursor)
        self.help_lbl.configure(cursor=cursor)

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

    def _snap_to_content(self, *, anchor: str = "topleft", deadband_px: int = 2):
        """
        Resize the window to exactly fit its content at the current scale.
        anchor: 'topleft' (default), 'center', 'topright'
        """
        self.root.update_idletasks()

        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()

        # Hard clamps (tune as you like)
        min_w, min_h = 220, 90
        max_w, max_h = 1800, 900
        w = max(min_w, min(max_w, req_w))
        h = max(min_h, min(max_h, req_h))

        x = self.root.winfo_x()
        y = self.root.winfo_y()
        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()

        # <-- DEAD BAND: do nothing if change is tiny
        if abs(w - cur_w) < deadband_px and abs(h - cur_h) < deadband_px:
            return

        if anchor == "center":
            x = x + (cur_w - w) // 2
            y = y + (cur_h - h) // 2
        elif anchor == "topright":
            x = x + (cur_w - w)

        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # Update aspect so future resizes remain consistent with content shape
        if h > 0:
            self._aspect = w / h


    def _set_text_color(self, color: str):
        # Main text
        self.title_lbl.configure(fg=color)
        self.time_lbl.configure(fg=color)
        self.sub_lbl.configure(fg=color)

        # Optional: also change the help label color
        # If you want help text to stay yellow always, leave this commented out.
        # self.help_lbl.configure(fg=color)


    # ----------------------------
    # Main update loop
    # ----------------------------

    def _tick(self):
        # CTRL+SHIFT => grab mode (black background); otherwise transparent
        grab = ctrl_shift_down_global()
        self._set_grab_mode(grab)

        now = datetime.now()
        title, subtitle, timer = compute_display(self.items, datetime.now())
        self.title_var.set(title)
        self.time_var.set("" if timer is None else timer)

        if subtitle:
            self.sub_var.set(subtitle)
            self._update_subtitle_layout(subtitle)

            # Choose an initial subtitle font size from your scaled default
            desired = max(self.sub_min_size, int(round(self.sub_font_base_size * self.scale * self.sub_ratio)))
            self.sub_font.configure(size=desired)

            self.root.update_idletasks()

            # Available vertical space is the gap frame height, so we control it.
            # First, compute the subtitle height at current font:
            sub_h = self.sub_font.metrics("linespace")

            # Add a little breathing room
            target_gap = sub_h + 4

            # Set gap height so subtitle has space
            self.gap_frame.configure(height=target_gap)
            self.root.update_idletasks()

            # Now "shrink-to-fit-gap" if needed (rare, but safe)
            gap_px = self.gap_frame.winfo_height()
            self._fit_subtitle_to_gap(gap_px)  # your existing method
            sub_h = self.sub_font.metrics("linespace")
            sub_w = self.sub_font.measure(subtitle)

            # Center subtitle inside the gap frame using place()
            gap_w = self.gap_frame.winfo_width()
            x = max(0, (gap_w - sub_w) // 2)
            y = max(0, (gap_px - sub_h) // 2)

            # Place relative to gap_frame (not root)
            self.sub_lbl.place(in_=self.gap_frame, relx=0.5, rely=0.5, anchor="center")
            self.sub_lbl.lift()
        else:
            self.sub_var.set("")
            self._update_subtitle_layout(None)
            self.sub_lbl.place_forget()
            self.gap_frame.configure(height=0)  # collapse the gap when no subtitle
            self._sub_size_current = None





        if self._grab_mode:
            t = self.time_var.get()
            if t != self._last_timer_text or self.scale != self._last_scale_for_help:
                #self._fit_help_text_to_timer()
                self._last_timer_text = t
                self._last_scale_for_help = self.scale

        changed = (title != self._last_title) or (timer != self._last_time)
        self._last_title, self._last_time = title, timer

        if self._mode is None and changed:
            self._snap_to_content(anchor="topleft")

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
