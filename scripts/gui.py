#!/usr/bin/env python3
"""Tkinter front end for the Google Maps Scraper Kit CLI."""
import datetime
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

KIT = Path(__file__).resolve().parent.parent
SCRAPER = KIT / "scripts" / "scrape.py"
ENGINE = KIT / "scripts" / "engine.py"


def build_scrape_command(keywords, city, depth, max_time, output, proxies, emails, socials):
    command = [sys.executable, "-u", str(SCRAPER), keywords[0]]
    for keyword in keywords[1:]:
        command.extend(["--keyword", keyword])
    command.extend(["--city", city, "--depth", str(depth), "--max-time", str(max_time),
                    "--out", str(output)])
    if not emails:
        command.append("--no-email")
    if not socials:
        command.append("--no-socials")
    for proxy in proxies:
        command.extend(["--proxy", proxy])
    return command


class ScraperGUI:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.process = None

        root.title("Google Maps Scraper Kit")
        root.geometry("820x760")
        root.minsize(680, 620)

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)

        ttk.Label(main, text="Konrad Scrapper Suite", font=("", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            main,
            text="Enter one search per line. The selected city centers the searches; the CLI saves a CSV.",
            wraplength=760,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))

        ttk.Label(main, text="Keywords").grid(row=2, column=0, sticky="nw", padx=(0, 8))
        self.keywords = ScrolledText(main, height=7, wrap="word")
        self.keywords.grid(row=2, column=1, columnspan=2, sticky="nsew", pady=(0, 8))

        ttk.Label(main, text="City / place").grid(row=3, column=0, sticky="w", padx=(0, 8))
        self.city = ttk.Entry(main)
        self.city.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(0, 8))
        self.city.insert(0, "Houston, TX")

        settings = ttk.Frame(main)
        settings.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Label(settings, text="Depth").pack(side="left")
        self.depth = ttk.Spinbox(settings, from_=1, to=100, width=6)
        self.depth.pack(side="left", padx=(6, 18))
        self.depth.set("5")
        ttk.Label(settings, text="Max time (seconds)").pack(side="left")
        self.max_time = ttk.Spinbox(settings, from_=1, to=86400, width=8)
        self.max_time.pack(side="left", padx=6)
        self.max_time.set("600")
        self.emails = tk.BooleanVar(value=True)
        self.socials = tk.BooleanVar(value=True)
        ttk.Checkbutton(settings, text="Find emails", variable=self.emails).pack(side="left", padx=(18, 4))
        ttk.Checkbutton(settings, text="Find social profiles", variable=self.socials).pack(side="left", padx=4)

        ttk.Label(main, text="Output folder").grid(row=5, column=0, sticky="w", padx=(0, 8))
        self.output_dir = ttk.Entry(main)
        self.output_dir.grid(row=5, column=1, sticky="ew", pady=(0, 8))
        self.output_dir.insert(0, str(KIT))
        ttk.Button(main, text="Browse…", command=self.choose_output_dir).grid(
            row=5, column=2, sticky="e", padx=(8, 0), pady=(0, 8))

        ttk.Label(main, text="Proxies (optional)").grid(row=6, column=0, sticky="nw", padx=(0, 8))
        self.proxies = ScrolledText(main, height=4, wrap="word")
        self.proxies.grid(row=6, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(
            main,
            text="One URL per line, e.g. http://host:port. Use provider-approved proxy URLs.",
            wraplength=760,
        ).grid(row=7, column=1, columnspan=2, sticky="w", pady=(0, 8))

        controls = ttk.Frame(main)
        controls.grid(row=8, column=0, columnspan=3, sticky="new", pady=(0, 8))
        self.run_button = ttk.Button(controls, text="Run scrape", command=self.run_scrape)
        self.run_button.pack(side="right")
        self.engine_button = ttk.Button(controls, text="Start engine", command=self.start_engine)
        self.engine_button.pack(side="right", padx=(0, 8))

        ttk.Label(main, text="Output / progress").grid(row=9, column=0, sticky="nw", padx=(0, 8))
        self.log = ScrolledText(main, height=12, state="disabled", wrap="word")
        self.log.grid(row=9, column=1, columnspan=2, sticky="nsew")
        main.rowconfigure(9, weight=1)
        self.append_log(f"Project folder: {KIT}\nStart the engine before scraping, or use “Start engine”.\n")
        root.after(100, self.drain_events)

    def choose_output_dir(self):
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or str(KIT))
        if folder:
            self.output_dir.delete(0, "end")
            self.output_dir.insert(0, folder)

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_process(self, command, label):
        if self.process is not None:
            messagebox.showinfo("Already running", "Wait for the current command to finish.")
            return
        try:
            self.process = subprocess.Popen(
                command,
                cwd=KIT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            self.append_log(f"Could not start {label}: {exc}\n")
            messagebox.showerror("Could not start", str(exc))
            return

        self.run_button.configure(state="disabled")
        self.engine_button.configure(state="disabled")
        self.append_log(f"\n▶ {label}\n")
        process = self.process

        def read_output():
            for line in process.stdout:
                self.events.put(("line", line))
            self.events.put(("done", process.wait()))

        threading.Thread(target=read_output, daemon=True).start()

    def start_engine(self):
        self.run_process([sys.executable, "-u", str(ENGINE), "start"], "Starting the local engine")

    def run_scrape(self):
        keywords = [line.strip() for line in self.keywords.get("1.0", "end").splitlines() if line.strip()]
        city = self.city.get().strip()
        output_dir = Path(self.output_dir.get().strip()).expanduser()
        proxies = [line.strip() for line in self.proxies.get("1.0", "end").splitlines() if line.strip()]
        try:
            depth = int(self.depth.get())
            max_time = int(self.max_time.get())
        except ValueError:
            messagebox.showerror("Invalid settings", "Depth and max time must be whole numbers.")
            return
        if not keywords:
            messagebox.showerror("Missing keywords", "Enter at least one keyword, one per line.")
            return
        if not city:
            messagebox.showerror("Missing city", "Enter the city or place for these searches.")
            return
        if depth < 1 or max_time < 1:
            messagebox.showerror("Invalid settings", "Depth and max time must be at least 1.")
            return
        if not output_dir.is_dir():
            messagebox.showerror("Invalid output folder", "Choose an existing output folder.")
            return

        slug = re.sub(r"[^a-z0-9]+", "-", keywords[0].lower()).strip("-")[:48] or "results"
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output = output_dir / f"{slug}-{timestamp}.csv"
        command = build_scrape_command(
            keywords, city, depth, max_time, output, proxies,
            self.emails.get(), self.socials.get(),
        )
        self.run_process(command, f"Scraping {len(keywords)} keyword(s); output: {output}")

    def drain_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "line":
                    self.append_log(value)
                else:
                    self.process = None
                    self.run_button.configure(state="normal")
                    self.engine_button.configure(state="normal")
                    self.append_log(f"\nProcess finished with exit code {value}.\n")
        except queue.Empty:
            pass
        self.root.after(100, self.drain_events)


def main():
    root = tk.Tk()
    ScraperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
