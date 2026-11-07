#!/usr/bin/env bash
# Launch the YouTube -> MP3 GUI using the project virtualenv.
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtualenv and installing yt-dlp..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -U pip -r requirements.txt
fi

exec .venv/bin/python YouTube_Downloader.py
