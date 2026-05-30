import os
import uuid
import shutil
import asyncio
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Lura Downloader API")

BASE_DOWNLOAD_PATH = "./downloads"
os.makedirs(BASE_DOWNLOAD_PATH, exist_ok=True)


class DownloadRequest(BaseModel):
    query: str  # song name, youtube link, or spotify link


def detect_source(query: str) -> list:
    if "youtube.com" in query or "youtu.be" in query:
        return [
            "yt-dlp", "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-metadata",
            "-o", "%(title)s.%(ext)s",
            query
        ]
    elif "spotify.com" in query:
        # yt-dlp can resolve spotify track names via youtube search
        return [
            "yt-dlp", "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-metadata",
            "-o", "%(title)s.%(ext)s",
            query
        ]
    else:
        # Plain search query
        return [
            "yt-dlp", "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-metadata",
            "-o", "%(title)s.%(ext)s",
            f"ytsearch1:{query}"
        ]


@app.get("/")
def root():
    return {"status": "Lura API is live 🎵"}


@app.get("/search")
async def search(q: str = Query(..., description="Song name to search")):
    """Returns top 5 search results from YouTube"""
    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            f"ytsearch5:{q}"
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if not stdout:
            raise HTTPException(status_code=404, detail="No results found")

        import json
        results = []
        for line in stdout.decode().strip().split("\n"):
            if line:
                data = json.loads(line)
                results.append({
                    "title": data.get("title"),
                    "channel": data.get("channel") or data.get("uploader"),
                    "duration": data.get("duration"),  # in seconds
                    "url": data.get("webpage_url"),
                    "thumbnail": data.get("thumbnail")
                })

        return {"results": results}

    except Exception as e:
        logging.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/download")
async def download(request: DownloadRequest):
    """Downloads audio and returns mp3 file"""
    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(BASE_DOWNLOAD_PATH, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        cmd = detect_source(request.query)

        # inject job_dir into output path
        cmd = [
            c.replace("%(title)s.%(ext)s", f"{job_dir}/%(title)s.%(ext)s")
            if "%(title)s" in c else c
            for c in cmd
        ]

        logging.info(f"Running: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        files = [f for f in os.listdir(job_dir) if f.endswith(".mp3")]

        if not files:
            shutil.rmtree(job_dir)
            logging.error(f"yt-dlp error: {stderr.decode()}")
            raise HTTPException(status_code=500, detail="Download failed — no mp3 found")

        mp3_path = os.path.join(job_dir, files[0])

        # FileResponse streams the file, cleanup after
        return FileResponse(
            path=mp3_path,
            media_type="audio/mpeg",
            filename=files[0],
            background=None
        )

    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        logging.error(f"Download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
def cleanup():
    shutil.rmtree(BASE_DOWNLOAD_PATH, ignore_errors=True)
