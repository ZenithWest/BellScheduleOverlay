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

def compute_display(items: List[Item], now: datetime) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Returns:
      title: main title line
      subtitle: None or "A → B" (shown only during transitions)
      timer: None or "H:MM:SS"
    """
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
                    return "Transitioning", f"{item.title} → {items[i+1].title}", fmt_hhmmss(nxt_dt - now)

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
                    return "Transitioning", f"{item.title} → {items[i+1].title}", fmt_hhmmss(nxt_dt - now)

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
    Subclasses a window proc.
    When CTRL+SHIFT is NOT held -> return HTTRANSPARENT on WM_NCHITTEST (click-through).
    When CTRL+SHIFT IS held -> behave normally (interactive).
    """
    def __init__(self, hwnd: int):
        if not is_windows():
            return

        import ctypes
        from ctypes import wintypes

        self.user32 = ctypes.windll.user32

        self.WM_NCHITTEST = 0x0084
        self.HTTRANSPARENT = -1
        self.GWLP_WNDPROC = -4

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

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

        self._hwnd = hwnd  # keep alive

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_NCHITTEST and not ctrl_shift_down_global():
            return self.HTTRANSPARENT
        return self._orig_wndproc(hwnd, msg, wparam, lparam)


def force_taskbar_icon(hwnd: int):
    """
    Force a borderless Tk window to show in the Windows taskbar.
    """
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

    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                       0x0001 | 0x0002 | 0x0020)  # SWP_NOSIZE|SWP_NOMOVE|SWP_FRAMECHANGED

def set_os_clickthrough(hwnd: int, enable: bool):
    """
    Toggle OS-level click-through using WS_EX_TRANSPARENT.
    Must be applied to BOTH the toplevel HWND and the Canvas HWND.
    """
    if not is_windows():
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020

    GetWindowLongW = user32.GetWindowLongW
    SetWindowLongW = user32.SetWindowLongW
    GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    GetWindowLongW.restype = ctypes.c_long
    SetWindowLongW.restype = ctypes.c_long

    exstyle = GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enable:
        exstyle |= WS_EX_TRANSPARENT
    else:
        exstyle &= ~WS_EX_TRANSPARENT

    SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

    # Force Windows to apply the style immediately
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0020)  # SWP_NOMOVE|SWP_NOSIZE|SWP_FRAMECHANGED


def _get_set_window_long_ptr():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW", None)
    SetWindowLongPtrW = getattr(user32, "SetWindowLongPtrW", None)

    if GetWindowLongPtrW and SetWindowLongPtrW:
        GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        GetWindowLongPtrW.restype = ctypes.c_void_p
        SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        SetWindowLongPtrW.restype = ctypes.c_void_p
        return GetWindowLongPtrW, SetWindowLongPtrW, True

    # 32-bit fallback
    GetWindowLongW = user32.GetWindowLongW
    SetWindowLongW = user32.SetWindowLongW
    GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongW.restype = ctypes.c_long
    SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    SetWindowLongW.restype = ctypes.c_long
    return GetWindowLongW, SetWindowLongW, False


def set_clickthrough(hwnd: int, enable: bool):
    """
    Enables/disables OS-level click-through for a specific HWND using WS_EX_TRANSPARENT.
    This is more reliable than WM_NCHITTEST for Tk child windows.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020

    GetWL, SetWL, is_ptr = _get_set_window_long_ptr()

    exstyle = GetWL(hwnd, GWL_EXSTYLE)
    # exstyle might be void* on 64-bit; normalize to int
    exstyle_int = int(exstyle) if exstyle is not None else 0

    if enable:
        exstyle_int |= WS_EX_TRANSPARENT
    else:
        exstyle_int &= ~WS_EX_TRANSPARENT

    if is_ptr:
        SetWL(hwnd, GWL_EXSTYLE, ctypes.c_void_p(exstyle_int))
    else:
        SetWL(hwnd, GWL_EXSTYLE, exstyle_int)

    # Force Windows to apply style changes immediately
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0020)  # SWP_NOMOVE|SWP_NOSIZE|SWP_FRAMECHANGED


def set_ws_ex_transparent(hwnd: int, enable: bool):
    """
    Toggle WS_EX_TRANSPARENT so the window becomes click-through at the OS level.
    """
    return
    if not is_windows():
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020

    GetWindowLongW = user32.GetWindowLongW
    SetWindowLongW = user32.SetWindowLongW
    GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    GetWindowLongW.restype = ctypes.c_long
    SetWindowLongW.restype = ctypes.c_long

    exstyle = GetWindowLongW(hwnd, GWL_EXSTYLE)

    # Always layered
    exstyle |= WS_EX_LAYERED

    if enable:
        exstyle |= WS_EX_TRANSPARENT
    else:
        exstyle &= ~WS_EX_TRANSPARENT

    SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

    # Force Windows to re-evaluate styles immediately
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0020)  # SWP_NOMOVE|SWP_NOSIZE|SWP_FRAMECHANGED


# ----------------------------
# Overlay UI (Canvas-based to ensure true click-through over text)
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

        # Transparency key (kept enabled)
        self.key_color = "#00FEFE"
        self.grab_bg = "#000000"
        self.grab_alpha = 0.5

        self.root.configure(bg=self.key_color)

        # Scaling
        self.scale = 1.0
        self.min_scale = 0.60
        self.max_scale = 10.00
        self.resize_margin = 12

        self.base_title_size = 18
        self.base_time_size = 34
        self.sub_font_base_size = 12
        self.sub_ratio = 0.75
        self.sub_min_size = 7

        self.base_help_size = 11
        self.help_ratio = 0.65
        self.help_min_size = 7

        self.padx_base = 10
        self.top_pad_base = 6
        self.gap_pad_base = 2
        self.bottom_pad_base = 6

        # Fonts
        self.title_font = tkfont.Font(family="Segoe UI", size=self.base_title_size, weight="bold")
        self.time_font  = tkfont.Font(family="Consolas", size=self.base_time_size, weight="bold")
        self.sub_font   = tkfont.Font(family="Segoe UI", size=self.sub_font_base_size, weight="bold")
        self.help_font  = tkfont.Font(family="Segoe UI", size=self.base_help_size, weight="bold")

        # Colors
        self.text_color = "white"
        self.help_color = "yellow"

        # Canvas (single drawable surface -> no separate label HWNDs blocking clicks)
        self.canvas = tk.Canvas(self.root, bg=self.key_color, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # Text items (centered)
        self.title_id = self.canvas.create_text(0, 0, text="Loading…", fill=self.text_color, font=self.title_font, anchor="n", justify="center")
        self.sub_id   = self.canvas.create_text(0, 0, text="", fill=self.text_color, font=self.sub_font,   anchor="n", justify="center", state="hidden")
        self.time_id  = self.canvas.create_text(0, 0, text="0:00:00", fill=self.text_color, font=self.time_font,  anchor="n", justify="center")
        self.help_id  = self.canvas.create_text(0, 0, text="CTRL+SHIFT+RightClick for Menu!", fill=self.help_color, font=self.help_font, anchor="n", justify="center", state="hidden")

        # Menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.color_menu = tk.Menu(self.menu, tearoff=0)
        colors = [
            ("White", "white"),
            ("Black", "black"),
            ("Yellow", "yellow"),
            ("Magenta", "magenta"),
            ("Green", "#7CFF00"),  # lime green
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
        self._resize_dir = None
        self._drag_off_x = 0
        self._drag_off_y = 0
        self._start_mouse_x = 0
        self._start_mouse_y = 0
        self._start_x = 0
        self._start_y = 0
        self._start_w = 0
        self._start_h = 0
        self._start_scale = 1.0

        self._grab_mode = False
        self._current_cursor = ""

        # Bindings (bind to canvas so it receives when interactive; root as backup)
        for w in (self.root, self.canvas):
            w.bind("<ButtonPress-1>", self._on_left_down)
            w.bind("<B1-Motion>", self._on_left_drag)
            w.bind("<ButtonRelease-1>", self._on_left_up)
            w.bind("<ButtonPress-3>", self._on_right_down)
            w.bind("<Motion>", self._on_motion_update_cursor)
            w.bind("<Leave>", self._on_leave_reset_cursor)

        self.root.bind("<Escape>", lambda e: self.root.destroy())

        # Place & realize
        self._place_top_right(20, 20)
        self.root.update()

        # Apply transparency key on the toplevel
        self.root.wm_attributes("-transparentcolor", self.key_color)

        # Install click-through by hit-test on BOTH the toplevel and the canvas HWND
        self._hit_tests = [
           WinClickThroughByHitTest(self.root.winfo_id()),
           WinClickThroughByHitTest(self.canvas.winfo_id()),

        ]

        self._hwnd_root = self.root.winfo_id()
        self._hwnd_canvas = self.canvas.winfo_id()

        self._click_hwnds = [self.root.winfo_id(), self.canvas.winfo_id()] #, 
#                            self.title_id, self.time_id, self.help_id, self.sub_id]



        if is_windows():
            force_taskbar_icon(self.root.winfo_id())
            #set_os_clickthrough(self._hwnd_root, True)
            #set_os_clickthrough(self._hwnd_canvas, True)
            #self.hwnd = self.root.winfo_id()
            #set_ws_ex_transparent(self.hwnd, True)  # start click-through
            for hwnd in self._click_hwnds:
                #set_os_clickthrough(hwnd, True)  # enable click-through when NOT grabbing
                set_ws_ex_transparent(hwnd, True)  # start click-through


        # Initial scale/layout
        self._apply_scale(self.scale)
        self._layout_and_snap(anchor="topleft")

        self._tick()

    def _apply_scale(self, scale: float):
        scale = max(self.min_scale, min(self.max_scale, scale))
        self.scale = scale

        self.title_font.configure(size=max(8, int(round(self.base_title_size * scale))))
        self.time_font.configure(size=max(10, int(round(self.base_time_size * scale))))

        sub_size = max(self.sub_min_size, int(round(self.sub_font_base_size * scale * self.sub_ratio)))
        self.sub_font.configure(size=sub_size)

        help_size = max(self.help_min_size, int(round(self.base_help_size * scale * self.help_ratio)))
        self.help_font.configure(size=help_size)


    def _fit_subtitle_to_gap(self, gap_px: int):
        """
        Shrink subtitle font (vertically) until its line height fits within gap_px.
        Stable: avoids rapid flip/flop by using hysteresis.
        """
        if gap_px <= 0:
            return

        # Desired subtitle size at current scale
        desired = int(round(self.sub_font_base_size * self.scale * self.sub_ratio))
        desired = max(self.sub_min_size, desired)

        # Track last applied size for stability
        if not hasattr(self, "_sub_size_current") or self._sub_size_current is None:
            self._sub_size_current = desired

        cur = self._sub_size_current

        # Apply current size to measure height
        self.sub_font.configure(size=cur)
        cur_h = self.sub_font.metrics("linespace")

        # Hysteresis (deadband) in pixels:
        # - shrink immediately if it doesn't fit
        # - only grow back if we have plenty of room (prevents oscillation)
        SHRINK_EPS = 0
        GROW_EPS = 6

        # If too tall -> shrink until it fits
        if cur_h > gap_px - SHRINK_EPS:
            s = cur
            while s > self.sub_min_size:
                s -= 1
                self.sub_font.configure(size=s)
                if self.sub_font.metrics("linespace") <= gap_px:
                    self._sub_size_current = s
                    return
            self._sub_size_current = self.sub_min_size
            self.sub_font.configure(size=self.sub_min_size)
            return

        # If it fits and we're below desired -> grow back cautiously
        if cur < desired and (gap_px - cur_h) >= GROW_EPS:
            s = cur
            while s < desired:
                ns = s + 1
                self.sub_font.configure(size=ns)
                if self.sub_font.metrics("linespace") <= gap_px:
                    s = ns
                    continue
                break
            self._sub_size_current = s
            self.sub_font.configure(size=s)
            return

        # Otherwise keep current size
        self._sub_size_current = cur
        self.sub_font.configure(size=cur)



    def _layout_and_snap(self, *, anchor: str = "topleft", deadband_px: int = 2):
        self.root.update_idletasks()

        cur_w = self.root.winfo_width()
        if cur_w <= 1:
            cur_w = 600

        padx = int(round(self.padx_base * self.scale))
        top_pad = int(round(self.top_pad_base * self.scale))
        gap_pad = int(round(self.gap_pad_base * self.scale))
        bottom_pad = int(round(self.bottom_pad_base * self.scale))

        sub_visible = (self.canvas.itemcget(self.sub_id, "state") == "normal")
        help_visible = (self.canvas.itemcget(self.help_id, "state") == "normal")

        cx = cur_w // 2

        # ----------------------------
        # LOCKED layout:
        # Title at fixed y
        # Timer at fixed y (not affected by subtitle)
        # Subtitle forced into the gap between title and timer
        # ----------------------------

        y_title = top_pad
        self.canvas.coords(self.title_id, cx, y_title)
        title_h = self.title_font.metrics("linespace")

        # Locked gap: always big enough for the subtitle line
        gap_between_title_and_timer = max(
            int(round(6 * self.scale)),                       # minimum breathing room
            self.sub_font.metrics("linespace") + gap_pad       # enough space for subtitle
        )
        y_timer = y_title + title_h + gap_between_title_and_timer
        self.canvas.coords(self.time_id, cx, y_timer)
        time_h = self.time_font.metrics("linespace")

        # Subtitle is drawn INSIDE the gap, without moving timer
        if sub_visible:
            gap_top = y_title + title_h
            gap_bottom = y_timer
            gap_px = gap_bottom - gap_top

            if gap_px > 0:
                # Try to shrink-to-fit-gap vertically
                if hasattr(self, "_fit_subtitle_to_gap"):
                    self._fit_subtitle_to_gap(gap_px)

                sub_h = self.sub_font.metrics("linespace")

                # If still doesn't fit, hide it (do NOT move timer)
                if sub_h > gap_px:
                    self.canvas.itemconfigure(self.sub_id, state="hidden")
                    sub_visible = False
                else:
                    y_sub = gap_top + (gap_px - sub_h) // 2
                    self.canvas.coords(self.sub_id, cx, y_sub)
            else:
                self.canvas.itemconfigure(self.sub_id, state="hidden")
                sub_visible = False

        # Help always comes AFTER timer
        y_help = y_timer + time_h + gap_pad
        if help_visible:
            self.canvas.coords(self.help_id, cx, y_help)

        # ----------------------------
        # Compute bbox of visible content for snapping
        # ----------------------------
        bbox = self.canvas.bbox(self.title_id, self.time_id)
        if bbox is None:
            return

        x0, y0, x1, y1 = bbox

        if sub_visible:
            b2 = self.canvas.bbox(self.sub_id)
            if b2:
                x0, y0, x1, y1 = min(x0, b2[0]), min(y0, b2[1]), max(x1, b2[2]), max(y1, b2[3])

        if help_visible:
            b3 = self.canvas.bbox(self.help_id)
            if b3:
                x0, y0, x1, y1 = min(x0, b3[0]), min(y0, b3[1]), max(x1, b3[2]), max(y1, b3[3])

        content_w = (x1 - x0) + 2 * padx
        content_h = (y1 - y0) + top_pad + bottom_pad

        min_w, min_h = 220, 90
        max_w, max_h = 1800, 900
        w = max(min_w, min(max_w, int(content_w)))
        h = max(min_h, min(max_h, int(content_h)))

        x = self.root.winfo_x()
        ywin = self.root.winfo_y()
        cur_w2 = self.root.winfo_width()
        cur_h2 = self.root.winfo_height()

        # ----------------------------
        # Deadband: if size change is tiny, avoid resizing window
        # Still recenter items based on actual current width.
        # ----------------------------
        if abs(w - cur_w2) < deadband_px and abs(h - cur_h2) < deadband_px:
            self.canvas.config(width=cur_w2, height=cur_h2)

            cx2 = cur_w2 // 2

            # Reapply locked coords using actual width
            y_title = top_pad
            self.canvas.coords(self.title_id, cx2, y_title)
            title_h = self.title_font.metrics("linespace")

            y_timer = y_title + title_h + gap_between_title_and_timer
            self.canvas.coords(self.time_id, cx2, y_timer)
            time_h = self.time_font.metrics("linespace")

            if sub_visible:
                gap_top = y_title + title_h
                gap_bottom = y_timer
                gap_px = gap_bottom - gap_top

                if gap_px > 0:
                    if hasattr(self, "_fit_subtitle_to_gap"):
                        self._fit_subtitle_to_gap(gap_px)
                    sub_h = self.sub_font.metrics("linespace")
                    if sub_h <= gap_px:
                        y_sub = gap_top + (gap_px - sub_h) // 2
                        self.canvas.coords(self.sub_id, cx2, y_sub)
                    else:
                        self.canvas.itemconfigure(self.sub_id, state="hidden")
                        sub_visible = False
                else:
                    self.canvas.itemconfigure(self.sub_id, state="hidden")
                    sub_visible = False

            if help_visible:
                y_help = y_timer + time_h + gap_pad
                self.canvas.coords(self.help_id, cx2, y_help)
            return

        # ----------------------------
        # Resize window & canvas
        # ----------------------------
        if anchor == "center":
            x = x + (cur_w2 - w) // 2
            ywin = ywin + (cur_h2 - h) // 2
        elif anchor == "topright":
            x = x + (cur_w2 - w)

        self.root.geometry(f"{w}x{h}+{x}+{ywin}")
        self.canvas.config(width=w, height=h)

        # Reapply locked coords with new width
        cx = w // 2
        y_title = top_pad
        self.canvas.coords(self.title_id, cx, y_title)
        title_h = self.title_font.metrics("linespace")

        y_timer = y_title + title_h + gap_between_title_and_timer
        self.canvas.coords(self.time_id, cx, y_timer)
        time_h = self.time_font.metrics("linespace")

        if sub_visible:
            gap_top = y_title + title_h
            gap_bottom = y_timer
            gap_px = gap_bottom - gap_top

            if gap_px > 0:
                if hasattr(self, "_fit_subtitle_to_gap"):
                    self._fit_subtitle_to_gap(gap_px)
                sub_h = self.sub_font.metrics("linespace")
                if sub_h <= gap_px:
                    y_sub = gap_top + (gap_px - sub_h) // 2
                    self.canvas.coords(self.sub_id, cx, y_sub)
                else:
                    self.canvas.itemconfigure(self.sub_id, state="hidden")
            else:
                self.canvas.itemconfigure(self.sub_id, state="hidden")

        if help_visible:
            y_help = y_timer + time_h + gap_pad
            self.canvas.coords(self.help_id, cx, y_help)


    def _set_grab_mode(self, grab: bool):
        if self._grab_mode == grab:
            return
        self._grab_mode = grab


        if is_windows() or True:
            # Normal mode -> click-through ON
            # Grab mode   -> click-through OFF (so drag/resize/menu works)
            #set_os_clickthrough(self._hwnd_root, enable=(not grab))
            #set_os_clickthrough(self._hwnd_canvas, enable=(not grab))
            for hwnd in getattr(self, "_click_hwnds", []):
                #set_clickthrough(hwnd, enable=(not grab))
                set_ws_ex_transparent(hwnd, enable=(not grab))

        if grab:
            self.root.attributes("-alpha", self.grab_alpha)
            self.canvas.configure(bg=self.grab_bg)
            self.canvas.itemconfigure(self.help_id, state="normal")
            self._set_cursor("fleur")
        else:
            self.root.attributes("-alpha", 1.0)
            self.canvas.configure(bg=self.key_color)
            self.canvas.itemconfigure(self.help_id, state="hidden")
            self._set_cursor("")
        self._layout_and_snap(anchor="topleft")

    def _pointer_in_root(self) -> tuple[int, int]:
        px = self.root.winfo_pointerx() - self.root.winfo_rootx()
        py = self.root.winfo_pointery() - self.root.winfo_rooty()
        return px, py

    def _hit_region(self, w: int, h: int, px: int, py: int) -> Optional[str]:
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

    def _set_cursor(self, cursor: str):
        if cursor == self._current_cursor:
            return
        self._current_cursor = cursor
        self.root.configure(cursor=cursor)
        self.canvas.configure(cursor=cursor)

    def _cursor_for_region(self, region: Optional[str]) -> str:
        if region is None:
            return "fleur"
        if region in ("lt", "rb"):
            return "size_nw_se"
        if region in ("rt", "lb"):
            return "size_ne_sw"
        if region in ("l", "r"):
            return "size_we"
        if region in ("t", "b"):
            return "size_ns"
        return "fleur"

    def _on_motion_update_cursor(self, _e):
        if not ctrl_shift_down_global():
            self._set_cursor("")
            return
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        px, py = self._pointer_in_root()
        region = self._hit_region(w, h, px, py)
        self._set_cursor(self._cursor_for_region(region))

    def _on_leave_reset_cursor(self, _e):
        if not ctrl_shift_down_global():
            self._set_cursor("")

    def _on_left_down(self, _e):
        if not ctrl_shift_down_global():
            return

        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()

        self._start_x, self._start_y, self._start_w, self._start_h = x, y, w, h
        self._start_mouse_x = self.root.winfo_pointerx()
        self._start_mouse_y = self.root.winfo_pointery()
        self._start_scale = self.scale

        px, py = self._pointer_in_root()
        region = self._hit_region(w, h, px, py)

        if region:
            self._mode = "resize"
            self._resize_dir = region
        else:
            self._mode = "move"
            self._resize_dir = None
            self._drag_off_x = self.root.winfo_pointerx() - x
            self._drag_off_y = self.root.winfo_pointery() - y

    def _on_left_drag(self, _e):
        if not ctrl_shift_down_global():
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

        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        dx = mx - self._start_mouse_x
        dy = my - self._start_mouse_y

        x0, y0, w0, h0 = self._start_x, self._start_y, self._start_w, self._start_h
        if w0 <= 0 or h0 <= 0:
            return

        right_edge = x0 + w0
        bottom_edge = y0 + h0

        proposed_w = w0
        proposed_h = h0
        d = self._resize_dir
        if "r" in d: proposed_w = w0 + dx
        if "l" in d: proposed_w = w0 - dx
        if "b" in d: proposed_h = h0 + dy
        if "t" in d: proposed_h = h0 - dy

        scale_w = proposed_w / w0
        scale_h = proposed_h / h0

        if d in ("l", "r"):
            s = scale_w
        elif d in ("t", "b"):
            s = scale_h
        else:
            s = scale_w if abs(scale_w - 1.0) >= abs(scale_h - 1.0) else scale_h

        new_scale = self._start_scale * s
        new_scale = max(self.min_scale, min(self.max_scale, new_scale))

        self._apply_scale(new_scale)
        self._layout_and_snap(anchor="topleft")

        self.root.update_idletasks()
        new_w = self.root.winfo_width()
        new_h = self.root.winfo_height()
        new_x = x0
        new_y = y0
        if "l" in d:
            new_x = right_edge - new_w
        if "t" in d:
            new_y = bottom_edge - new_h
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

    def _set_text_color(self, color: str):
        self.text_color = color
        for item in (self.title_id, self.sub_id, self.time_id):
            self.canvas.itemconfigure(item, fill=color)

    def _place_top_right(self, mx: int, my: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = max(220, self.root.winfo_reqwidth())
        x = max(0, sw - w - mx)
        y = my
        self.root.geometry(f"+{x}+{y}")

    def _tick(self):
        grab = ctrl_shift_down_global()
        self._set_grab_mode(grab)

        title, subtitle, timer = compute_display(self.items, datetime.now())
        self.canvas.itemconfigure(self.title_id, text=title)
        self.canvas.itemconfigure(self.time_id, text="" if timer is None else timer)

        if subtitle:
            self.canvas.itemconfigure(self.sub_id, text=subtitle, state="normal")
        else:
            self.canvas.itemconfigure(self.sub_id, text="", state="hidden")

        # Always lay out so subtitle never sits at (0,0).
        # While dragging/resizing, use a huge deadband so we don't fight the window geometry.
        if self._mode is None:
            self._layout_and_snap(anchor="topleft")
        else:
            self._layout_and_snap(anchor="topleft", deadband_px=10**9)


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
