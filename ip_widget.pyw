
import os
import re
import json
import queue
import threading
import ipaddress
import urllib.request
from pathlib import Path
from datetime import datetime
import tkinter as tk

INTERVAL = 300_000  # 5 minutes

API_LIST = [
    "https://myip.ipip.net",
    "http://ip.3322.net",
]

DATA_DIR = Path(
    os.environ.get("LOCALAPPDATA") or Path.home()
) / "IPWidget"

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"


def load_state():
    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}


def get_public_ip():
    errors = []

    for url in API_LIST:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "IPWidget/1.0"}
            )

            with urllib.request.urlopen(
                request, timeout=5
            ) as response:
                text = response.read(512).decode(
                    "utf-8", errors="replace"
                )

            matches = re.findall(
                r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
                text
            )

            for candidate in matches:
                address = ipaddress.IPv4Address(candidate)
                if address.is_global:
                    return str(address)

            raise ValueError("No public IPv4 found")

        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("; ".join(errors))


class IPWidget:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Public IP Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        self.bg = "#17212b"
        self.fg = "#ffffff"
        self.muted = "#9ba9b7"

        self.root.configure(bg=self.bg)

        self.state = load_state()
        self.current = self.state.get("current", "--")
        self.previous = self.state.get("previous", "--")

        x = self.state.get(
            "x", self.root.winfo_screenwidth() - 290
        )
        y = self.state.get("y", 50)

        self.root.geometry(f"265x155+{x}+{y}")

        self.results = queue.Queue()
        self.checking = False

        self.build_ui()
        self.build_menu()

        self.root.after(100, self.process_results)
        self.root.after(500, self.schedule_refresh)

    def build_ui(self):
        header = tk.Frame(self.root, bg=self.bg)
        header.pack(fill="x", padx=12, pady=(8, 3))

        title = tk.Label(
            header, text="● Public IP Monitor",
            font=("Segoe UI", 10, "bold"),
            bg=self.bg, fg=self.fg
        )
        title.pack(side="left")

        close = tk.Label(
            header, text="✕",
            font=("Segoe UI", 11),
            bg=self.bg, fg=self.muted,
            cursor="hand2"
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.root.destroy())

        for widget in (header, title):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<ButtonRelease-1>", self.end_drag)

        tk.Label(
            self.root, text="CURRENT IPv4",
            font=("Segoe UI", 8),
            bg=self.bg, fg=self.muted,
            anchor="w"
        ).pack(fill="x", padx=14)

        self.current_label = tk.Label(
            self.root, text=self.current,
            font=("Consolas", 16, "bold"),
            bg=self.bg, fg="#79d2ff",
            anchor="w"
        )
        self.current_label.pack(fill="x", padx=14)

        tk.Label(
            self.root, text="PREVIOUS IPv4",
            font=("Segoe UI", 8),
            bg=self.bg, fg=self.muted,
            anchor="w"
        ).pack(fill="x", padx=14)

        self.previous_label = tk.Label(
            self.root, text=self.previous,
            font=("Consolas", 11),
            bg=self.bg, fg=self.fg,
            anchor="w"
        )
        self.previous_label.pack(fill="x", padx=14)

        self.status = tk.Label(
            self.root, text="Waiting...",
            font=("Segoe UI", 8),
            bg=self.bg, fg=self.muted,
            anchor="w"
        )
        self.status.pack(fill="x", padx=14, pady=(5, 0))

    def build_menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label="Refresh now", command=self.refresh
        )
        menu.add_command(
            label="Toggle always on top",
            command=self.toggle_topmost
        )
        menu.add_separator()
        menu.add_command(
            label="Exit", command=self.root.destroy
        )

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        self.root.bind("<Button-3>", show_menu)

    def start_drag(self, event):
        self.dx = event.x_root - self.root.winfo_x()
        self.dy = event.y_root - self.root.winfo_y()

    def drag(self, event):
        x = event.x_root - self.dx
        y = event.y_root - self.dy
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, event):
        self.save_state()

    def toggle_topmost(self):
        current = bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", not current)

    def save_state(self):
        data = {
            "current": self.current,
            "previous": self.previous,
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
        }
        STATE_FILE.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8"
        )

    def fetch_worker(self):
        try:
            ip = get_public_ip()
            self.results.put(("success", ip))
        except Exception as exc:
            self.results.put(("error", str(exc)))

    def refresh(self):
        if self.checking:
            return

        self.checking = True
        self.status.config(text="Checking IP...")

        threading.Thread(
            target=self.fetch_worker,
            daemon=True
        ).start()

    def schedule_refresh(self):
        self.refresh()
        self.root.after(INTERVAL, self.schedule_refresh)

    def process_results(self):
        try:
            while True:
                status, value = self.results.get_nowait()
                self.checking = False

                if status == "success":
                    if value != self.current:
                        if self.current != "--":
                            self.previous = self.current
                        self.current = value

                        self.current_label.config(text=self.current)
                        self.previous_label.config(
                            text=self.previous
                        )
                        self.save_state()

                    now = datetime.now().strftime("%H:%M:%S")
                    self.status.config(
                        text=f"Updated {now}  |  5 min",
                        fg="#80d6a0"
                    )
                else:
                    self.status.config(
                        text="Query failed - retry in 5 min",
                        fg="#ffae83"
                    )

        except queue.Empty:
            pass

        self.root.after(200, self.process_results)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    IPWidget().run()
