"""Small local image store for kitchen and portion photos.

Images arrive as base64 data URLs (the browser downsizes them first), are
checked by magic bytes and size, and are written under ``settings.media_dir``,
which the API serves at ``/media``.
"""

import base64
import binascii
import re
import uuid
from pathlib import Path

from app.config import settings
from app.domain.exceptions import BadRequestError

MAX_IMAGE_BYTES = 4 * 1024 * 1024
DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", re.DOTALL)
MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def media_root() -> Path:
    root = Path(settings.media_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def decode_image(data_url: str) -> tuple[bytes, str]:
    match = DATA_URL.match(data_url.strip())
    if match is None:
        raise BadRequestError("image must be a JPEG, PNG or WebP data URL")
    mime, encoded = match.groups()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadRequestError("image data is not valid base64") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise BadRequestError("image is larger than 4 MB")
    if not any(raw.startswith(prefix) for prefix in MAGIC[mime]):
        raise BadRequestError("image content does not match its type")
    return raw, mime


def save_image(kind: str, owner_id: uuid.UUID, raw: bytes, mime: str) -> str:
    folder = media_root() / kind / str(owner_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{EXTENSION[mime]}"
    (folder / name).write_bytes(raw)
    return f"/media/{kind}/{owner_id}/{name}"
