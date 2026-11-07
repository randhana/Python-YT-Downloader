# YouTube Playlist → MP3

A small Tkinter GUI app that takes a YouTube **playlist** (or single video) URL
and downloads every track as a high-quality **MP3** into a folder of your choice.

- Downloading: [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
- MP3 conversion + metadata/cover art: **FFmpeg**

## Requirements

- Python 3.8+ with Tkinter (`python3-tk` on Debian/Ubuntu)
- FFmpeg on your PATH (`sudo apt install ffmpeg`)

## Run

```bash
./run.sh
```

The first run creates a `.venv/` and installs `yt-dlp`. After that it just
launches the app. To run it manually:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U -r requirements.txt
.venv/bin/python YouTube_Downloader.py
```

## Using the app

1. Paste a playlist or video URL.
2. Choose the output folder (defaults to `~/Music/YT-MP3`).
3. Pick a bitrate (320 / 256 / 192 / 128 kbps).
4. Click **Download**. Progress, status and a per-track log are shown; **Cancel**
   stops after the current track. Unavailable videos are skipped automatically.

Each MP3 is tagged with title metadata and the video thumbnail as cover art.

## Note

Only download content you have the right to download, and follow YouTube's Terms
of Service.
