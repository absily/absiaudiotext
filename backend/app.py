"""ABSI Audio Cloud: authenticated Piper text-to-speech generation and R2 upload."""
from __future__ import annotations

import hmac
import logging
import threading
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("absi_audio")
_generate_lock = threading.Lock()

app = FastAPI(title="ABSI Audio Cloud", docs_url=None, redoc_url=None)
MAX_CHARS = int(os.getenv("MAX_CHARS", "18000"))
VOICE_PATH = os.getenv("VOICE_PATH", "/app/models/ar_JO-kareem-medium.onnx")

class Article(BaseModel):
    url: str = Field(min_length=20, max_length=800)
    html: str = Field(min_length=1, max_length=100000)

def article_key(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ("www.absi.cc", "absi.cc"):
        raise ValueError("Article must use https://www.absi.cc")
    match = re.fullmatch(r"/(20\d{2})/(0[1-9]|1[0-2])/([A-Za-z0-9_-]+)\.html", u.path)
    if not match:
        raise ValueError("Invalid Blogger article URL")
    return f"articles/{match[1]}/{match[2]}/{match[3]}.mp3"

def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "iframe", "noscript", "svg", "form", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def chunks(text: str, length: int = 500) -> list[str]:
    parts = re.split(r"(?<=[.!؟؛:])\s+", text)
    result: list[str] = []
    buffer = ""
    for part in parts:
        while len(part) > length:
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append(part[:length])
            part = part[length:]
        if len(buffer) + len(part) + 1 > length and buffer:
            result.append(buffer)
            buffer = ""
        buffer = (buffer + " " + part).strip()
    if buffer:
        result.append(buffer)
    return result

def r2_client():
    needed = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if any(not os.getenv(x) for x in needed):
        raise RuntimeError("R2 is not configured")
    return boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

def make_mp3(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        wavs: list[str] = []
        for idx, part in enumerate(chunks(text)):
            wav = str(Path(td) / f"{idx:04}.wav")
            process = subprocess.run(
                ["piper", "--model", VOICE_PATH, "--output_file", wav],
                input=part + "\n", text=True, capture_output=True, timeout=120,
            )
            if process.returncode != 0:
                raise RuntimeError("Piper speech generation failed")
            wavs.append(wav)
        if not wavs:
            raise ValueError("No article text")
        concat = Path(td) / "concat.txt"
        concat.write_text("".join(f"file '{f}'\n" for f in wavs), encoding="utf-8")
        target = Path(td) / "output.mp3"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
             "-codec:a", "libmp3lame", "-b:a", "64k", str(target)],
            check=True, timeout=120,
        )
        return target.read_bytes()

@app.get("/health")
def health():
    return {"ok": True, "voice_present": Path(VOICE_PATH).exists()}

@app.post("/generate")
def generate(article: Article, authorization: str | None = Header(default=None)):
    token = os.getenv("WORKER_SHARED_SECRET", "")
    if not token or not authorization or not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        key = article_key(article.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = clean_text(article.html)
    if len(content) < 30:
        raise HTTPException(status_code=422, detail="Article text too short")
    if len(content) > MAX_CHARS:
        raise HTTPException(status_code=422, detail=f"Article contains {len(content)} characters; limit is {MAX_CHARS}. No partial recording created.")
    if not _generate_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Audio generation already in progress; retry later")
    try:
        s3 = r2_client()
        try:
            s3.head_object(Bucket=os.environ["R2_BUCKET"], Key=key)
            return {"status": "already_exists", "key": key}
        except ClientError as ex:
            status = ex.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status != 404:
                raise
        audio = make_mp3(content)
        if not audio.startswith(b"ID3") and not (len(audio) >= 2 and audio[0] == 0xff and (audio[1] & 0xe0) == 0xe0):
            raise RuntimeError("Generated output is not an MP3 file")
        s3.put_object(Bucket=os.environ["R2_BUCKET"], Key=key, Body=audio,
                      ContentType="audio/mpeg", CacheControl="public, max-age=86400",
                      Metadata={"source": "absi.cc"})
        return {"status": "created", "key": key, "bytes": len(audio), "chars": len(content)}
    except Exception as exc:
        logger.exception("Audio generation failed for %s", key)
        raise HTTPException(status_code=503, detail="Audio generation unavailable; check server logs") from exc
    finally:
        _generate_lock.release()
