"""
Admin-added media that makes a project look better in the app: an icon (logo), a cover image and video links.
Images are uploaded to our backend (Salesforce's image URLs are mostly empty) and served at /media/<file>.
Videos are links (YouTube, Vimeo, ...) rather than uploads: they play smoothly on phones and cost no storage.
"""

import json
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AdminUser, AuditLog, ProjectMedia
from app.salesforce.base import Record

KINDS = ("icon", "cover")
MAX_VIDEOS = 10
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class MediaError(ValueError):
    """Bad upload or link; the message is shown to the admin."""


def media_dir() -> Path:
    path = Path(get_settings().media_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_url(filename: str | None) -> str | None:
    """Relative to the API base, so it works through any tunnel or domain the apps use."""
    return f"/media/{filename}" if filename else None


def _image_ext(data: bytes) -> str:
    """Trust the bytes, not the file name or browser-sent type."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise MediaError("Use a PNG, JPG or WebP image.")


def youtube_id(url: str) -> str | None:
    u = urlparse(url)
    host = (u.hostname or "").removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        candidate = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            candidate = (parse_qs(u.query).get("v") or [""])[0]
        else:
            parts = u.path.strip("/").split("/")
            candidate = parts[1] if len(parts) > 1 and parts[0] in ("embed", "shorts", "live", "v") else ""
    else:
        return None
    return candidate if YOUTUBE_ID.match(candidate) else None


def _video_out(v: dict) -> dict:
    yt = youtube_id(v["url"])
    return {
        "Id": v["id"],
        "Title": v["title"],
        "URL__c": v["url"],
        "Thumbnail_URL__c": f"https://img.youtube.com/vi/{yt}/hqdefault.jpg" if yt else None,
    }


def as_json(row: ProjectMedia | None) -> dict:
    """The admin portal's view of a project's media."""
    videos = json.loads(row.videos) if row and row.videos else []
    return {
        "iconUrl": media_url(row.icon_file) if row else None,
        "coverUrl": media_url(row.cover_file) if row else None,
        "videos": [_video_out(v) for v in videos],
    }


def media_by_project(db: Session) -> dict[str, ProjectMedia]:
    return {m.sf_project_id: m for m in db.scalars(select(ProjectMedia))}


def with_media(project: Record, row: ProjectMedia | None) -> Record:
    """Adds the admin's media to a Salesforce project. An uploaded cover replaces Salesforce's image."""
    m = as_json(row)
    return {
        **project,
        "Icon_URL__c": m["iconUrl"],
        "Cover_Image_URL__c": m["coverUrl"] or project.get("Cover_Image_URL__c"),
        "Videos": m["videos"],
    }


def with_media_all(db: Session, projects: list[Record]) -> list[Record]:
    rows = media_by_project(db)
    return [with_media(p, rows.get(p["Id"])) for p in projects]


def _row(db: Session, project_id: str, admin: AdminUser) -> ProjectMedia:
    row = db.get(ProjectMedia, project_id) or ProjectMedia(sf_project_id=project_id, videos="[]")
    row.updated_by = admin.id
    db.add(row)
    return row


def _remove_file(filename: str | None) -> None:
    if filename:
        (media_dir() / filename).unlink(missing_ok=True)


def save_image(db: Session, project: Record, kind: str, data: bytes, admin: AdminUser) -> ProjectMedia:
    """Stores a new icon/cover and drops the old file. Caller commits."""
    if kind not in KINDS:
        raise MediaError("Unknown image type.")
    settings = get_settings()
    limit_kb = settings.media_icon_max_kb if kind == "icon" else settings.media_cover_max_kb
    if not data:
        raise MediaError("The file is empty.")
    if len(data) > limit_kb * 1024:
        raise MediaError(f"The image is too large. The limit is {limit_kb // 1024 or 1} MB.")
    filename = f"{secrets.token_hex(16)}.{_image_ext(data)}"  # unguessable and unique, so it can be cached forever
    (media_dir() / filename).write_bytes(data)

    row = _row(db, project["Id"], admin)
    old = getattr(row, f"{kind}_file")
    setattr(row, f"{kind}_file", filename)
    db.add(AuditLog(admin_id=admin.id, action=f"project_{kind}_upload", detail=project.get("Name")))
    _remove_file(old)
    return row


def remove_image(db: Session, project: Record, kind: str, admin: AdminUser) -> ProjectMedia:
    if kind not in KINDS:
        raise MediaError("Unknown image type.")
    row = _row(db, project["Id"], admin)
    _remove_file(getattr(row, f"{kind}_file"))
    setattr(row, f"{kind}_file", None)
    db.add(AuditLog(admin_id=admin.id, action=f"project_{kind}_remove", detail=project.get("Name")))
    return row


def set_videos(db: Session, project: Record, videos: list[dict], admin: AdminUser) -> ProjectMedia:
    """Replaces the project's video links, in the given order. Caller commits."""
    if len(videos) > MAX_VIDEOS:
        raise MediaError(f"Add at most {MAX_VIDEOS} videos.")
    clean = []
    for i, v in enumerate(videos, start=1):
        title = (v.get("title") or "").strip()
        url = (v.get("url") or "").strip()
        u = urlparse(url)
        if u.scheme != "https" or not u.hostname:
            raise MediaError(f"Video {i}: enter a full https:// link (e.g. a YouTube link).")
        if not title:
            raise MediaError(f"Video {i}: add a title.")
        clean.append({"id": v.get("id") or secrets.token_hex(6), "title": title[:80], "url": url[:500]})
    row = _row(db, project["Id"], admin)
    row.videos = json.dumps(clean)
    db.add(AuditLog(admin_id=admin.id, action="project_videos", detail=f"{project.get('Name')}: {len(clean)} video(s)"))
    return row
