"""
The upload safety gate — safe_ingest() is the ONLY entry point for any
uploaded image anywhere in this app. No current or future code path may
hand raw upload bytes to a model, disk, or the compositor without going
through here first.

Pipeline, in order (each stage can reject before the next one runs):
  1. Size cap (streamed read, doesn't trust Content-Length) + magic-byte
     type sniffing (never trusts the extension or client-supplied MIME type).
  2. Decompression-bomb protection (Pillow's own guard + an explicit
     dimension cap).
  3. Metadata stripping — rebuilds a fresh Image with an empty .info dict,
     so no EXIF/GPS/ICC data can survive, entirely in memory.
  4. Content moderation (see uploads/moderation.py).

Deliberately never writes the original upload to disk: everything above
happens in memory, so there is no window where raw bytes sit on disk and
no cleanup path to get wrong. uploads/retention.py exists for future code
paths (e.g. Phase 3 video) that fundamentally need a real file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, ImageOps

from config import get_settings
from uploads.moderation import moderate_image

# Defense-in-depth pixel-count cap, in addition to the explicit per-side
# check below (catches extreme-aspect-ratio images that dodge a per-side
# check, e.g. 30000x2000). Set once at import time — PIL.Image.MAX_IMAGE_PIXELS
# is global process state, not per-call.
Image.MAX_IMAGE_PIXELS = 8000 * 8000


class IngestRejected(Exception):
    """Base class for any safe_ingest() rejection."""


class UploadRejected(IngestRejected):
    """Non-content-safety rejection: size, type, dimensions, or a corrupt/
    unreadable file. `reason` is a short machine-readable code, safe to log."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ModerationRejected(IngestRejected):
    """Content-safety rejection. `category` is for logging ONLY — the
    category must never be echoed back to the user (generic refusal only)."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(f"moderation_rejected:{category}")


@dataclass
class CleanImage:
    """The only representation of an uploaded image that's allowed to reach
    a model, the compositor, or any other downstream code. Guaranteed to be
    a freshly re-encoded, metadata-free, moderation-passed, size/dimension-
    validated Pillow Image."""

    image: Image.Image
    width: int
    height: int
    content_type: str            # sniffed from magic bytes, never client-supplied
    source_filename: str | None  # original filename — LOGGING ONLY, never used as a path


_SIGNATURE_JPEG = b"\xff\xd8\xff"
_SIGNATURE_PNG = b"\x89PNG\r\n\x1a\n"


def _sniff_content_type(head: bytes) -> str | None:
    """Magic-byte type detection — never trusts the extension or the
    client-supplied Content-Type header."""
    if head.startswith(_SIGNATURE_JPEG):
        return "image/jpeg"
    if head.startswith(_SIGNATURE_PNG):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Stream the body in chunks with a running counter, rejecting as soon
    as the cap is exceeded — doesn't trust Content-Length, which is
    client-supplied and can lie or be absent."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadRejected("file_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_and_verify(data: bytes) -> Image.Image:
    """Pillow's own validation, layered on top of the magic-byte check, per
    the master prompt's explicitly-allowed fallback. verify() invalidates
    the Image object for further use, so the file must be reopened and
    forced through a full pixel decode (.load()) afterward — verify() alone
    misses some truncated/corrupt files."""
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
    except Image.DecompressionBombError as exc:
        raise UploadRejected("decompression_bomb") from exc
    except Exception as exc:
        raise UploadRejected("invalid_image") from exc

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:
        raise UploadRejected("decompression_bomb") from exc
    except Exception as exc:
        raise UploadRejected("invalid_image") from exc
    return img


def _strip_metadata(img: Image.Image) -> Image.Image:
    """Rebuild a brand-new Image from raw pixel bytes. The new object's
    .info dict is empty by construction — no EXIF/GPS/ICC profile from the
    source can survive, because the new object was never told about it."""
    img = ImageOps.exif_transpose(img) or img
    mode = "RGBA" if img.mode in ("RGBA", "LA") else "RGB"
    img = img.convert(mode)
    return Image.frombytes(img.mode, img.size, img.tobytes())


async def safe_ingest(upload: UploadFile) -> CleanImage:
    """The only entry point for any uploaded image. Raises UploadRejected or
    ModerationRejected on failure; never writes the original bytes to disk."""
    settings = get_settings()

    data = await _read_capped(upload, settings.max_image_bytes)

    content_type = _sniff_content_type(data[:16])
    if content_type is None:
        raise UploadRejected("unrecognized_file_type")

    img = _decode_and_verify(data)

    if img.width > settings.max_image_dimension_px or img.height > settings.max_image_dimension_px:
        raise UploadRejected("dimensions_too_large")

    clean_img = _strip_metadata(img)

    moderation = await moderate_image(clean_img)
    if not moderation.passed:
        raise ModerationRejected(moderation.category or "unknown")

    return CleanImage(
        image=clean_img,
        width=clean_img.width,
        height=clean_img.height,
        content_type=content_type,
        source_filename=upload.filename,
    )
