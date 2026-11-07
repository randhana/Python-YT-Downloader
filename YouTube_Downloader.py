#!/usr/bin/env python3
"""
YouTube Playlist -> MP3 downloader (GUI, with a download queue).

Features
--------
* Paste a playlist (or single video) URL and add it to a queue.
* Each playlist is saved into its OWN sub-folder inside the chosen location.
* Queue runs one playlist at a time; the next starts automatically when one
  finishes. You can also Start manually.
* Pause / Resume (pauses the current track and resumes it) and Stop.
* Detailed, real-time log: which track, per-track % + speed/ETA, and overall
  "track X of N" + queue progress.
* High-quality MP3 (selectable bitrate) with title metadata + cover art.

Needs: yt-dlp (in .venv) and FFmpeg on PATH.
Run:   .venv/bin/python YouTube_Downloader.py     (or ./run.sh)
"""

import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import yt_dlp
    from yt_dlp.utils import sanitize_filename
except ImportError:
    raise SystemExit(
        "yt-dlp is not installed.\n"
        "Install it with:  .venv/bin/python -m pip install -U yt-dlp\n"
        "and run this app with:  .venv/bin/python YouTube_Downloader.py"
    )

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def human(num):
    """Bytes -> human readable."""
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


class StopWorker(Exception):
    """Raised internally to abort the queue worker cleanly."""


class DownloaderApp:
    # queue item statuses
    QUEUED, RUNNING, DONE, ERROR, PAUSED = (
        "Queued", "Downloading", "Done", "Error", "Paused",
    )

    def __init__(self, root):
        self.root = root
        self.msg_queue = queue.Queue()

        self.items = []           # list of dicts (queue entries)
        self.lock = threading.Lock()
        self.worker = None
        self.pause_event = threading.Event()   # set = run, clear = pause
        self.pause_event.set()
        self.stop_event = threading.Event()
        self.current_id = None

        root.title("YouTube Playlist → MP3  (queue)")
        root.geometry("820x680")
        root.minsize(660, 560)
        pad = {"padx": 8, "pady": 4}

        # ---------------- input row ----------------
        tk.Label(root, text="Playlist / video URL:").grid(
            row=0, column=0, sticky="w", **pad)
        self.url_var = tk.StringVar()
        url_entry = tk.Entry(root, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky="we", **pad)
        url_entry.bind("<Return>", lambda e: self.add_to_queue())
        tk.Button(root, text="Add to queue", command=self.add_to_queue).grid(
            row=0, column=2, sticky="we", **pad)

        tk.Label(root, text="Save location:").grid(
            row=1, column=0, sticky="w", **pad)
        self.folder_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Music", "YT-MP3"))
        tk.Entry(root, textvariable=self.folder_var).grid(
            row=1, column=1, sticky="we", **pad)
        tk.Button(root, text="Browse…", command=self.choose_folder).grid(
            row=1, column=2, sticky="we", **pad)

        tk.Label(root, text="MP3 quality:").grid(
            row=2, column=0, sticky="w", **pad)
        self.quality_var = tk.StringVar(value="320")
        qframe = tk.Frame(root)
        qframe.grid(row=2, column=1, sticky="w", **pad)
        ttk.Combobox(qframe, textvariable=self.quality_var, width=8,
                     state="readonly",
                     values=["320", "256", "192", "128"]).pack(side="left")
        tk.Label(qframe, text="kbps").pack(side="left", padx=6)

        # ---------------- control row ----------------
        ctl = tk.Frame(root)
        ctl.grid(row=3, column=0, columnspan=3, sticky="we", padx=8, pady=4)
        self.start_btn = tk.Button(ctl, text="▶ Start", width=10,
                                   command=self.start_queue)
        self.pause_btn = tk.Button(ctl, text="⏸ Pause", width=10,
                                   command=self.pause, state="disabled")
        self.resume_btn = tk.Button(ctl, text="⏵ Resume", width=10,
                                    command=self.resume, state="disabled")
        self.stop_btn = tk.Button(ctl, text="⏹ Stop", width=10,
                                  command=self.stop, state="disabled")
        self.remove_btn = tk.Button(ctl, text="Remove", width=9,
                                    command=self.remove_selected)
        self.clear_btn = tk.Button(ctl, text="Clear finished", width=12,
                                   command=self.clear_finished)
        for b in (self.start_btn, self.pause_btn, self.resume_btn,
                  self.stop_btn, self.remove_btn, self.clear_btn):
            b.pack(side="left", padx=3)

        # ---------------- queue table ----------------
        tframe = tk.Frame(root)
        tframe.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=4)
        cols = ("name", "status", "progress")
        self.tree = ttk.Treeview(tframe, columns=cols, show="headings", height=7)
        self.tree.heading("name", text="Playlist / Video")
        self.tree.heading("status", text="Status")
        self.tree.heading("progress", text="Tracks")
        self.tree.column("name", width=460, anchor="w")
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("progress", width=120, anchor="center")
        tsb = tk.Scrollbar(tframe, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # ---------------- current activity ----------------
        self.now_var = tk.StringVar(value="Idle.")
        tk.Label(root, textvariable=self.now_var, anchor="w",
                 font=("TkDefaultFont", 10, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="we", padx=8)

        self.track_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.track_var, anchor="w").grid(
            row=6, column=0, columnspan=3, sticky="we", padx=8)
        self.song_bar = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.song_bar.grid(row=7, column=0, columnspan=3, sticky="we",
                           padx=8, pady=(0, 2))

        self.overall_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.overall_var, anchor="w").grid(
            row=8, column=0, columnspan=3, sticky="we", padx=8)
        self.overall_bar = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.overall_bar.grid(row=9, column=0, columnspan=3, sticky="we",
                             padx=8, pady=(0, 4))

        # ---------------- log ----------------
        lframe = tk.Frame(root)
        lframe.grid(row=10, column=0, columnspan=3, sticky="nsew", padx=8, pady=4)
        lsb = tk.Scrollbar(lframe)
        lsb.pack(side="right", fill="y")
        self.log = tk.Text(lframe, height=9, wrap="word", state="disabled",
                           yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        lsb.config(command=self.log.yview)

        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(4, weight=1)
        root.grid_rowconfigure(10, weight=2)

        self.update_buttons()
        self.root.after(80, self.process_queue)

    # ================= message plumbing =================
    def put(self, kind, payload=None):
        self.msg_queue.put((kind, payload))

    def log_msg(self, text):
        self.put("log", ANSI_RE.sub("", str(text)))

    def process_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", payload + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif kind == "now":
                    self.now_var.set(payload)
                elif kind == "track":
                    self.track_var.set(payload)
                elif kind == "song":
                    self.song_bar["value"] = payload
                elif kind == "overall_text":
                    self.overall_var.set(payload)
                elif kind == "overall":
                    self.overall_bar["value"] = payload
                elif kind == "refresh":
                    self.render_tree()
                elif kind == "buttons":
                    self.update_buttons()
        except queue.Empty:
            pass
        self.root.after(80, self.process_queue)

    # ================= queue table =================
    def render_tree(self):
        with self.lock:
            snapshot = list(self.items)
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for it in snapshot:
            prog = f"{it['done']}/{it['total']}" if it["total"] else "—"
            if it["errors"]:
                prog += f"  ({it['errors']} err)"
            self.tree.insert("", "end", iid=it["id"],
                             values=(it["name"], it["status"], prog))
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def add_to_queue(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a YouTube URL.")
            return
        item = {
            "id": str(time.time_ns()),
            "url": url,
            "name": url,          # replaced with real title once resolved
            "status": self.QUEUED,
            "total": 0, "done": 0, "errors": 0,
        }
        with self.lock:
            self.items.append(item)
        self.url_var.set("")
        self.log_msg(f"➕ Added to queue: {url}")
        self.put("refresh")
        # resolve the real name/count in the background (nice display)
        threading.Thread(target=self.resolve_meta, args=(item,),
                         daemon=True).start()

    def resolve_meta(self, item):
        try:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                    "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(item["url"], download=False)
            if not info:
                return
            with self.lock:
                if "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    item["name"] = info.get("title") or item["url"]
                    item["total"] = len(entries)
                else:
                    item["name"] = info.get("title") or item["url"]
                    item["total"] = 1
            self.put("refresh")
        except Exception:
            pass  # leave the URL as the display name

    def remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        removed = 0
        with self.lock:
            keep = []
            for it in self.items:
                if it["id"] in sel and it["status"] != self.RUNNING:
                    removed += 1
                else:
                    keep.append(it)
            self.items = keep
        if removed:
            self.log_msg(f"🗑 Removed {removed} item(s) from the queue.")
        else:
            self.log_msg("Cannot remove the item that is currently downloading.")
        self.put("refresh")

    def clear_finished(self):
        with self.lock:
            self.items = [it for it in self.items
                          if it["status"] not in (self.DONE, self.ERROR)]
        self.put("refresh")

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or "~")
        if folder:
            self.folder_var.set(folder)

    # ================= buttons / state =================
    def worker_alive(self):
        return self.worker is not None and self.worker.is_alive()

    def update_buttons(self):
        running = self.worker_alive()
        paused = running and not self.pause_event.is_set()
        self.start_btn.config(state="disabled" if running else "normal")
        self.pause_btn.config(
            state="normal" if (running and not paused) else "disabled")
        self.resume_btn.config(state="normal" if paused else "disabled")
        self.stop_btn.config(state="normal" if running else "disabled")

    def start_queue(self):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Missing folder", "Choose a save location.")
            return
        with self.lock:
            has_work = any(it["status"] == self.QUEUED for it in self.items)
        if not has_work:
            messagebox.showinfo("Queue empty",
                                "Add at least one playlist/URL to the queue.")
            return
        if self.worker_alive():
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", f"Cannot create folder:\n{exc}")
            return
        self.stop_event.clear()
        self.pause_event.set()
        self.worker = threading.Thread(target=self.run_queue,
                                       args=(folder, self.quality_var.get()),
                                       daemon=True)
        self.worker.start()
        self.log_msg("▶ Queue started.")
        self.put("buttons")

    def pause(self):
        self.pause_event.clear()
        self.log_msg("⏸ Pause requested — will pause the current track…")
        self.put("buttons")

    def resume(self):
        self.pause_event.set()
        self.log_msg("⏵ Resumed.")
        self.put("buttons")

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()   # unblock any pause wait
        self.log_msg("⏹ Stop requested — finishing current track then halting…")
        self.put("buttons")

    # ================= worker =================
    def _progress_hook(self, d):
        if d["status"] == "downloading":
            if self.stop_event.is_set() or not self.pause_event.is_set():
                raise yt_dlp.utils.DownloadCancelled()
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            if total:
                self.put("song", done / total * 100)
            speed = (d.get("_speed_str") or "").strip()
            eta = (d.get("_eta_str") or "").strip()
            size = f"{human(done)}/{human(total)}" if total else human(done)
            self.put("track", f"      {size}   {speed}   ETA {eta}")
        elif d["status"] == "finished":
            self.put("song", 100)
            self.put("track", "      Converting to MP3…")

    def run_queue(self, base_folder, quality):
        try:
            while not self.stop_event.is_set():
                # pause between items
                self._wait_if_paused()
                if self.stop_event.is_set():
                    break
                with self.lock:
                    item = next((x for x in self.items
                                 if x["status"] == self.QUEUED), None)
                    queued_left = sum(1 for x in self.items
                                      if x["status"] == self.QUEUED)
                    total_items = len(self.items)
                if item is None:
                    break
                self.current_id = item["id"]
                self._process_item(item, base_folder, quality, total_items)
        except StopWorker:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_msg(f"Worker error: {exc}")
        finally:
            self.current_id = None
            self.put("now", "Idle.")
            self.put("track", "")
            self.put("song", 0)
            if self.stop_event.is_set():
                self.log_msg("⏹ Stopped.")
            else:
                self.log_msg("✅ Queue finished — nothing left to download.")
            self.put("overall_text", "")
            self.put("overall", 0)
            self.put("buttons")

    def _wait_if_paused(self):
        if not self.pause_event.is_set():
            self.put("now", "Paused.")
            self.put("buttons")
        while not self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.15)

    def _process_item(self, item, base_folder, quality, total_items):
        item["status"] = self.RUNNING
        item["done"] = 0
        item["errors"] = 0
        self.put("refresh")
        self.put("buttons")

        # --- figure out the entries + target sub-folder ---
        self.put("now", f"Reading: {item['name']}")
        self.log_msg(f"\n▶ Reading '{item['name']}' …")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "extract_flat": "in_playlist",
                                   "skip_download": True}) as probe:
                info = probe.extract_info(item["url"], download=False)
        except Exception as exc:  # noqa: BLE001
            item["status"] = self.ERROR
            item["errors"] += 1
            self.log_msg(f"   ✗ Could not read URL: {exc}")
            self.put("refresh")
            return

        if info is None:
            item["status"] = self.ERROR
            item["errors"] += 1
            self.log_msg("   ✗ Could not read that URL.")
            self.put("refresh")
            return

        is_playlist = "entries" in info
        if is_playlist:
            entries = [e for e in info["entries"] if e]
            playlist_name = info.get("title") or "playlist"
            sub = sanitize_filename(playlist_name, restricted=False) or "playlist"
            target = os.path.join(base_folder, sub)
        else:
            entries = [info]
            playlist_name = info.get("title") or "video"
            target = base_folder  # single video -> straight into the location

        os.makedirs(target, exist_ok=True)
        item["name"] = playlist_name
        item["total"] = len(entries)
        self.put("refresh")
        self.log_msg(f"   📁 Saving to: {target}")
        self.log_msg(f"   🎵 {len(entries)} track(s) found.")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(target, "%(title)s.%(ext)s"),
            "ignoreerrors": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "continuedl": True,
            "download_archive": os.path.join(target, ".downloaded.txt"),
            "progress_hooks": [self._progress_hook],
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": quality},
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
        }

        total = len(entries)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for idx, entry in enumerate(entries, 1):
                if self.stop_event.is_set():
                    item["status"] = self.QUEUED   # resume later (archive skips done)
                    self.put("refresh")
                    raise StopWorker
                title = entry.get("title") or entry.get("id") or "unknown"
                vurl = (entry.get("webpage_url") or entry.get("url")
                        or entry.get("id"))

                self.put("now", f"{item['name']}   ·   track {idx}/{total}")
                self.put("track", f"   ♪  {title}")
                self.put("song", 0)
                self.put("overall_text",
                         f"Playlist progress: track {idx} of {total}   "
                         f"·   {item['done']} saved, {item['errors']} error(s)")
                self.put("overall", (idx - 1) / total * 100)
                self.log_msg(f"   [{idx}/{total}] {title}")

                ok = self._download_one(ydl, vurl, title)
                if ok == "stopped":
                    item["status"] = self.QUEUED
                    self.put("refresh")
                    raise StopWorker
                elif ok:
                    item["done"] += 1
                else:
                    item["errors"] += 1
                self.put("refresh")
                self.put("overall", idx / total * 100)

        item["status"] = self.DONE
        self.put("overall", 100)
        self.put("overall_text",
                 f"Playlist done: {item['done']} ok, {item['errors']} error(s)")
        self.log_msg(f"   ✅ '{item['name']}': {item['done']} saved, "
                     f"{item['errors']} error(s).")
        self.put("refresh")

    def _download_one(self, ydl, vurl, title):
        """Download one track. Returns True/False, or 'stopped'. Pause-aware."""
        while True:
            if self.stop_event.is_set():
                return "stopped"
            try:
                ydl.download([vurl])
                self.log_msg(f"        ✓ saved")
                return True
            except yt_dlp.utils.DownloadCancelled:
                if self.stop_event.is_set():
                    return "stopped"
                # paused mid-track: wait, then retry (resumes the partial file)
                self.put("now", "Paused.")
                self.log_msg("        ⏸ paused — waiting to resume…")
                self.put("buttons")
                while (not self.pause_event.is_set()
                       and not self.stop_event.is_set()):
                    time.sleep(0.15)
                if self.stop_event.is_set():
                    return "stopped"
                self.log_msg("        ⏵ resuming…")
                self.put("buttons")
                # loop retries the same track
            except Exception as exc:  # noqa: BLE001
                self.log_msg(f"        ✗ failed: {exc}")
                return False


def main():
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
