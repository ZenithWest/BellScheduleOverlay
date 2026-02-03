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

            # "title,time" (single time) - allowed for first and possibly last, per your rules
            if len(parts) == 2:
                title, t = parts
                items.append(Item(title=title, t1=parse_hhmm(t), t2=None))
            # "title,begin,end"
            elif len(parts) >= 3:
                title, t1, t2 = parts[0], parts[1], parts[2]
                items.append(Item(title=title, t1=parse_hhmm(t1), t2=parse_hhmm(t2)))
            else:
                # ignore weird lines
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
    # Always show H:MM:SS (hours can be 0+)
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    h = total // 3600
    rem = total % 3600
    m = rem // 60
    s = rem % 60
    return f"{h:d}:{m:02d}:{s:02d}"

def compute_display(items: List[Item], now: datetime) -> Tuple[str, Optional[str]]:
    """
    Returns (title_text, timer_text_or_None).
    If timer_text_or_None is None => show only title/message (e.g., transitioning).
    """
    # Walk schedule to find state
    for i, item in enumerate(items):
        begin = dt_today(item.t1)
        end = dt_today(item.t2) if item.t2 else None

        if end is None:
            # single-time item
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)
            else:
                nxt = next_begin_of(items, i)
                if nxt is not None:
                    nxt_dt = dt_today(nxt)
                    last_dt = begin
                    if last_dt <= now < nxt_dt:
                        return f"Transitioning from {item.title} to {items[i+1].title}", None
                # else: keep scanning; this item could be last and already passed
        else:
            # two-time item
            if now < begin:
                return item.title, fmt_hhmmss(begin - now)
            elif begin <= now < end:
                return item.title, fmt_hhmmss(end - now)
            else:
                # after end, maybe transitioning until next begin
                nxt = next_begin_of(items, i)
                if nxt is not None:
                    nxt_dt = dt_today(nxt)
                    if end <= now < nxt_dt:
                        return f"Transitioning from {item.title} to {items[i+1].title}", None
                # else: keep scanning; could be last and already passed

    # Past the last time of the last item => show elapsed since that last time
    last_item = items[-1]
    last_dt = dt_today(last_time_of(last_item))
    if now >= last_dt:
        return "End of School", fmt_hhmmss(now - last_dt)

    # Fallback (shouldn't happen)
    return "Schedule", None

# ----------------------------
# Overlay UI (Tkinter)
# ----------------------------

class OverlayApp:
    def __init__(self, schedule_path: str):
        self.items = load_schedule(schedule_path)

        self.root = tk.Tk()
        self.root.title("Overlay Countdown")

        # Make it borderless and always-on-top
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Transparent background trick
        self.transparent_color = "#ff00ff"  # magenta key
        self.root.configure(bg=self.transparent_color)

        # Try true transparency (best on Windows)
        self._enable_transparency()

        # Fonts / labels
        self.title_var = tk.StringVar(value="")
        self.time_var = tk.StringVar(value="")

        self.title_lbl = tk.Label(
            self.root,
            textvariable=self.title_var,
            fg="white",
            bg=self.transparent_color,
            font=("Segoe UI", 18, "bold"),
            padx=10,
            pady=2
        )
        self.title_lbl.pack()

        self.time_lbl = tk.Label(
            self.root,
            textvariable=self.time_var,
            fg="white",
            bg=self.transparent_color,
            font=("Consolas", 34, "bold"),
            padx=10,
            pady=0
        )
        self.time_lbl.pack()

        # Position: top-right with a margin
        self._place_top_right(margin_x=20, margin_y=20)

        # Optional: allow closing with Esc
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self._tick()

    def _enable_transparency(self):
        system = platform.system().lower()
        try:
            # Works well on Windows
            self.root.wm_attributes("-transparentcolor", self.transparent_color)
        except tk.TclError:
            # Fallback: slightly transparent window (Linux/macOS commonly)
            # Note: This makes the whole window translucent rather than "only text visible".
            try:
                self.root.attributes("-alpha", 0.85)
            except tk.TclError:
                pass

    def _place_top_right(self, margin_x: int, margin_y: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        # Start with minimal size; it grows after text set
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        x = max(0, sw - w - margin_x)
        y = margin_y
        self.root.geometry(f"+{x}+{y}")

    def _tick(self):
        now = datetime.now()
        title, timer = compute_display(self.items, now)

        self.title_var.set(title)
        self.time_var.set("" if timer is None else timer)

        # Reposition after size changes (e.g., "Transitioning..." is wider)
        self._place_top_right(margin_x=20, margin_y=20)

        # Update ~5x/second
        self.root.after(200, self._tick)

    def run(self):
        self.root.mainloop()

def main():
    # Default to the uploaded sample file path if not provided
    default_path = ".\\Bell-Schedule.txt"
    schedule_path = sys.argv[1] if len(sys.argv) > 1 else default_path

    if not os.path.exists(schedule_path):
        print(f"Schedule file not found: {schedule_path}")
        print("Usage: python overlay_timer.py path/to/schedule.csv")
        sys.exit(1)

    app = OverlayApp(schedule_path)
    app.run()

if __name__ == "__main__":
    main()
