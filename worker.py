import os
import threading
from yt_dlp import YoutubeDL

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

jobs_lock = threading.Lock()
jobs = {}


def get_lock():
    return jobs_lock


def get_jobs():
    return jobs


def clean_url(url):
    if not url:
        return ""
    import re
    match = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([^&?/]+)", url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return url.strip()


def _format_size(num):
    if not num:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


# -------------------- VIDEO INFO -------------------- #
def get_video_info(url):
    url = clean_url(url)
    if not url:
        return {"error": "Invalid URL"}

    try:
        with YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "url": url,
        }

    except Exception as e:
        return {"error": str(e)}


# -------------------- FORMATS -------------------- #
def get_formats(url):
    url = clean_url(url)
    if not url:
        return {"error": "Invalid URL"}

    try:
        with YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        formats_map = {}

        for f in info.get("formats", []):
            h = f.get("height") or 0
            if h > 0 and f.get("vcodec") != "none":
                size = f.get("filesize") or f.get("filesize_approx") or 0
                if h not in formats_map or size > formats_map[h][1]:
                    formats_map[h] = (f["format_id"], size)

        resolutions = [
            (2160, "4K"),
            (1440, "1440p"),
            (1080, "1080p"),
            (720, "720p"),
            (480, "480p"),
            (360, "360p"),
        ]

        result = []

        for height, label in resolutions:
            available = [h for h in formats_map.keys() if h <= height]
            if available:
                closest = max(available)
                _, size = formats_map[closest]

                result.append({
                    "id": f"bestvideo[height<={height}]",
                    "label": label,
                    "resolution": label,
                    "ext": "mp4",
                    "size": _format_size(size),
                })

        # MP3 option
        result.insert(0, {
            "id": "mp3",
            "label": "MP3 Audio",
            "resolution": "Audio Only",
            "ext": "mp3",
            "size": "~5 MB",
        })

        return result

    except Exception as e:
        return {"error": str(e)}


# -------------------- PROGRESS -------------------- #
def _progress_hook(job_id):
    def hook(d):
        with jobs_lock:
            if job_id not in jobs:
                return

            if d["status"] == "downloading":
                pct = d.get("_percent_str", "0%").replace("%", "").strip()
                try:
                    pct = float(pct)
                except:
                    pct = 0

                jobs[job_id].update({
                    "progress": pct,
                    "status": "downloading",
                    "speed": d.get("_speed_str"),
                    "eta": d.get("_eta_str"),
                })

            elif d["status"] == "finished":
                jobs[job_id]["status"] = "processing"

    return hook


# -------------------- DOWNLOAD -------------------- #
def start_download(job_id, url, format_id):
    t = threading.Thread(
        target=_download_thread,
        args=(job_id, url, format_id),
        daemon=True
    )
    t.start()


def _download_thread(job_id, url, format_id):
    url = clean_url(url)

    with jobs_lock:
        jobs[job_id] = {
            "progress": 0,
            "status": "starting",
            "file": None,
            "error": None,
            "speed": None,
            "eta": None,
        }

    outtmpl = os.path.join(
        DOWNLOAD_FOLDER,
        "%(title)s [%(id)s].%(ext)s"
    )

    ydl_opts = {
        "outtmpl": outtmpl,
        "progress_hooks": [_progress_hook(job_id)],
        "quiet": True,
        "merge_output_format": "mp4",
    }

    # 🔥 FIXED FORMAT HANDLING
    if format_id == "mp3":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        # video + audio merge (IMPORTANT FIX)
        ydl_opts["format"] = f"{format_id}+bestaudio/best"

    try:
        before = set(os.listdir(DOWNLOAD_FOLDER))

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        after = set(os.listdir(DOWNLOAD_FOLDER))
        new_files = after - before

        filename = None

        if new_files:
            filename = list(new_files)[0]
        else:
            files = [
                f for f in os.listdir(DOWNLOAD_FOLDER)
                if os.path.isfile(os.path.join(DOWNLOAD_FOLDER, f))
            ]
            if files:
                filename = max(
                    files,
                    key=lambda f: os.path.getmtime(
                        os.path.join(DOWNLOAD_FOLDER, f)
                    )
                )

        if filename:
            with jobs_lock:
                jobs[job_id].update({
                    "status": "done",
                    "progress": 100,
                    "file": filename,
                })
        else:
            _mark_error(job_id, "File not found after download")

    except Exception as e:
        _mark_error(job_id, str(e))


def _mark_error(job_id, msg):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update({
                "status": "error",
                "error": str(msg),
            })


def cancel_job(job_id):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["status"] = "cancelled"
            return True
    return False
