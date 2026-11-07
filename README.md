# YouTube Playlist → MP3

A small Tkinter GUI app that downloads YouTube **playlists** (or single videos)
as high-quality **MP3** files, with a **download queue** and **parallel**
downloading.

- Downloading: [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
- MP3 conversion + metadata/cover art: **FFmpeg**

## Features

- **Queue** several playlists/URLs; the next starts automatically when one
  finishes (or start manually).
- Each playlist is saved into its **own sub-folder** inside your save location.
- **Parallel downloads** — download several tracks at once, and conversion of
  one track overlaps the download of others (no waiting one-by-one).
- **Pause / Resume** (resumes the partial track) and **Stop**.
- Live status: which tracks are active with per-track %, plus overall
  "track X of N" and per-playlist progress.
- Selectable MP3 bitrate (320 / 256 / 192 / 128 kbps), with title metadata and
  the video thumbnail embedded as cover art.
- A per-folder download archive means re-running skips tracks you already have.

## Requirements

- Python 3.9+ with Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu)
- FFmpeg on your PATH (`sudo apt install ffmpeg`)

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U -r requirements.txt
```

## Run

```bash
.venv/bin/python YouTube_Downloader.py
```

## Using the app

1. Paste a playlist or video URL and click **Add to queue** (or press Enter).
   Add as many as you like.
2. Choose the **save location** (defaults to `~/Music/YT-MP3`). Each playlist
   gets its own sub-folder here.
3. Pick the **MP3 quality** and how many tracks to download in **Parallel**
   (3–4 is a good balance; higher can be faster but may hit YouTube rate limits).
4. Click **▶ Start**. Use **⏸ Pause / ⏵ Resume** and **⏹ Stop** as needed.
   Failed/unavailable tracks are skipped and counted; just re-run to retry them.

## Notes

- **Parallel count:** more isn't always better. If you see failed tracks or
  `HTTP 429` errors, lower the parallel count. Already-downloaded tracks are
  skipped on re-run.
- Only download content you have the right to download, and follow YouTube's
  Terms of Service.
