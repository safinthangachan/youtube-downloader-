from flask import Flask, request, jsonify, render_template, send_from_directory
import os, uuid, time

from worker import (
    get_video_info,
    get_formats,
    start_download,
    cancel_job,
    get_jobs,
    get_lock,
    DOWNLOAD_FOLDER,
    clean_url,
)

app = Flask(__name__)

MAX_CONCURRENT_DOWNLOADS = 3


def safe_json():
    try:
        return request.get_json(force=True) or {}
    except:
        return {}


def error(msg, code=400):
    return jsonify({"success": False, "error": msg}), code


def success(data):
    return jsonify({"success": True, **data})


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/info", methods=["POST"])
def info():
    data = safe_json()
    url = clean_url(data.get("url"))

    if not url:
        return error("Invalid URL")

    res = get_video_info(url)
    if "error" in res:
        return error(res["error"], 500)

    return success(res)


@app.route("/formats", methods=["POST"])
def formats():
    data = safe_json()
    url = clean_url(data.get("url"))

    if not url:
        return error("Invalid URL")

    res = get_formats(url)
    if "error" in res:
        return error(res["error"], 500)

    return success({"formats": res})


@app.route("/start", methods=["POST"])
def start():
    data = safe_json()
    url = clean_url(data.get("url"))
    format_id = data.get("format_id")

    if not url or not format_id:
        return error("Missing data")

    with get_lock():
        active = sum(1 for j in get_jobs().values()
                     if j.get("status") in ("starting", "downloading"))

        if active >= MAX_CONCURRENT_DOWNLOADS:
            return error("Too many downloads", 429)

        job_id = str(uuid.uuid4())
        get_jobs()[job_id] = {
            "progress": 0,
            "status": "starting",
            "file": None,
            "error": None,
            "speed": None,
            "eta": None,
        }

    start_download(job_id, url, format_id)
    return success({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    with get_lock():
        j = get_jobs().get(job_id)

    if not j:
        return error("Invalid job", 404)

    return success(j)


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    return success({"cancelled": cancel_job(job_id)})


@app.route("/file/<job_id>")
def file(job_id):
    with get_lock():
        j = get_jobs().get(job_id)

    if not j or not j.get("file"):
        return error("File not ready", 404)

    return send_from_directory(DOWNLOAD_FOLDER, j["file"], as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
