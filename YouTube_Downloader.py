#!/usr/bin/env python3
"""
YouTube Playlist -> MP3 downloader (small GUI app).

Paste a YouTube playlist (or single video) URL, pick an output folder and
quality, and download every track as an MP3. Uses yt-dlp for downloading and
FFmpeg for the MP3 conversion.

Run with the project virtualenv:
    .venv/bin/python YouTube_Downloader.py
"""

import os
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Strips ANSI colour codes that yt-dlp puts in its messages.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

try:
    import yt_dlp
except ImportError:
    raise SystemExit(
        "yt-dlp is not installed.\n"
        "Install it with:  .venv/bin/python -m pip install -U yt-dlp\n"
        "and run this app with:  .venv/bin/python YouTube_Downloader.py"
    )


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.msg_queue = queue.Queue()
        self.worker = None
        self.cancel_flag = threading.Event()

        root.title("YouTube Playlist → MP3")
        root.geometry("680x520")
        root.minsize(560, 440)

        pad = {"padx": 10, "pady": 6}

        # --- URL ---
        tk.Label(root, text="Playlist / video URL:").grid(
            row=0, column=0, sticky="w", **pad
        )
        self.url_var = tk.StringVar()
        tk.Entry(root, textvariable=self.url_var).grid(
            row=0, column=1, columnspan=2, sticky="we", **pad
        )

        # --- Output folder ---
        tk.Label(root, text="Save to folder:").grid(
            row=1, column=0, sticky="w", **pad
        )
        self.folder_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Music", "YT-MP3")
        )
        tk.Entry(root, textvariable=self.folder_var).grid(
            row=1, column=1, sticky="we", **pad
        )
        tk.Button(root, text="Browse…", command=self.choose_folder).grid(
            row=1, column=2, sticky="we", **pad
        )

        # --- Quality ---
        tk.Label(root, text="MP3 quality:").grid(row=2, column=0, sticky="w", **pad)
        self.quality_var = tk.StringVar(value="320")
        quality_box = ttk.Combobox(
            root,
            textvariable=self.quality_var,
            values=["320", "256", "192", "128"],
            state="readonly",
            width=10,
        )
        quality_box.grid(row=2, column=1, sticky="w", **pad)
        tk.Label(root, text="kbps").grid(row=2, column=1, sticky="w", padx=90)

        # --- Buttons ---
        btn_frame = tk.Frame(root)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky="we", padx=10, pady=4)
        self.download_btn = tk.Button(
            btn_frame, text="Download", width=14, command=self.start_download
        )
        self.download_btn.pack(side="left")
        self.cancel_btn = tk.Button(
            btn_frame, text="Cancel", width=10, command=self.cancel_download,
            state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=6)

        # --- Progress ---
        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.progress.grid(row=4, column=0, columnspan=3, sticky="we", padx=10, pady=4)
        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(root, textvariable=self.status_var, anchor="w").grid(
            row=5, column=0, columnspan=3, sticky="we", padx=10
        )

        # --- Log ---
        log_frame = tk.Frame(root)
        log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", padx=10, pady=6)
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log = tk.Text(log_frame, height=12, wrap="word", state="disabled",
                           yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log.yview)

        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(6, weight=1)

        self.root.after(100, self.process_queue)

    # ---------- UI helpers ----------
    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or "~")
        if folder:
            self.folder_var.set(folder)

    def log_msg(self, text):
        self.msg_queue.put(("log", ANSI_RE.sub("", text)))

    def set_status(self, text):
        self.msg_queue.put(("status", text))

    def set_progress(self, value):
        self.msg_queue.put(("progress", value))

    def process_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", payload + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    self._on_finished(payload)
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    # ---------- download control ----------
    def start_download(self):
        url = self.url_var.get().strip()
        folder = self.folder_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a YouTube URL.")
            return
        if not folder:
            messagebox.showwarning("Missing folder", "Please choose an output folder.")
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", f"Cannot create folder:\n{exc}")
            return

        self.cancel_flag.clear()
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress["value"] = 0
        self.set_status("Starting…")

        self.worker = threading.Thread(
            target=self.run_download,
            args=(url, folder, self.quality_var.get()),
            daemon=True,
        )
        self.worker.start()

    def cancel_download(self):
        self.cancel_flag.set()
        self.set_status("Cancelling…")

    def _on_finished(self, summary):
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        ok, total, errors = summary
        if self.cancel_flag.is_set():
            self.set_status(f"Cancelled. {ok}/{total} completed.")
        else:
            self.set_status(f"Done. {ok}/{total} downloaded, {errors} error(s).")
            messagebox.showinfo(
                "Finished",
                f"Downloaded {ok} of {total} track(s).\n"
                f"{errors} error(s).\nSaved to:\n{self.folder_var.get()}",
            )

    # ---------- worker thread ----------
    def _progress_hook(self, d):
        if self.cancel_flag.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            if total:
                self.set_progress(done / total * 100)
            title = d.get("info_dict", {}).get("title", "")
            speed = d.get("_speed_str", "").strip()
            self.set_status(f"Downloading: {title}  {speed}")
        elif d["status"] == "finished":
            self.set_progress(100)
            self.set_status("Converting to MP3…")

    def run_download(self, url, folder, quality):
        ok = errors = total = 0

        class _Logger:
            def __init__(self, app):
                self.app = app
                self._seen_warnings = set()

            def debug(self, msg):
                clean = ANSI_RE.sub("", msg)
                if clean.startswith("[download] Downloading item"):
                    self.app.log_msg(clean)

            def info(self, msg):
                self.app.log_msg(ANSI_RE.sub("", msg))

            def warning(self, msg):
                clean = ANSI_RE.sub("", msg)
                # Collapse the noisy "no JS runtime" warning to a single line.
                if "JavaScript runtime" in clean or "js-runtimes" in clean:
                    if "jsruntime" in self._seen_warnings:
                        return
                    self._seen_warnings.add("jsruntime")
                    clean = ("No JS runtime found; using audio-only formats "
                             "(fine for MP3). Install 'deno' to silence this.")
                self.app.log_msg("WARNING: " + clean)

            def error(self, msg):
                self.app.log_msg("ERROR: " + ANSI_RE.sub("", msg))

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(folder, "%(title)s.%(ext)s"),
            "ignoreerrors": True,          # skip a bad video, keep going
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,           # follow playlists
            "logger": _Logger(self),
            "progress_hooks": [self._progress_hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality,
                },
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.log_msg(f"Fetching info for:\n{url}")
                info = ydl.extract_info(url, download=False)

                if info is None:
                    self.log_msg("Could not read that URL.")
                    self.msg_queue.put(("done", (0, 0, 1)))
                    return

                entries = info["entries"] if "entries" in info else [info]
                entries = [e for e in entries if e]  # drop unavailable
                total = len(entries)
                self.log_msg(f"Found {total} item(s).")

                for idx, entry in enumerate(entries, 1):
                    if self.cancel_flag.is_set():
                        break
                    title = entry.get("title", entry.get("id", "unknown"))
                    self.set_status(f"[{idx}/{total}] {title}")
                    self.log_msg(f"[{idx}/{total}] {title}")
                    self.set_progress(0)
                    video_url = entry.get("webpage_url") or entry.get("url") or \
                        entry.get("id")
                    try:
                        ydl.download([video_url])
                        ok += 1
                        self.log_msg(f"    ✓ saved")
                    except yt_dlp.utils.DownloadCancelled:
                        break
                    except Exception as exc:  # noqa: BLE001 - keep going on bad item
                        errors += 1
                        self.log_msg(f"    ✗ failed: {exc}")

        except yt_dlp.utils.DownloadCancelled:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_msg(f"Fatal error: {exc}")
            errors += 1

        self.msg_queue.put(("done", (ok, total, errors)))


def main():
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
