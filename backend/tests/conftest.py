"""
Shared fixtures for the Phase 0 safety-gate tests. Every fixture is
synthesized in-test via Pillow — no binary files are committed to the repo.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from PIL import Image


def _upload(data: bytes, filename: str = "photo.jpg") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


@pytest.fixture
def tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def tiny_jpeg_upload(tiny_jpeg_bytes) -> UploadFile:
    return _upload(tiny_jpeg_bytes, "photo.jpg")


@pytest.fixture
def oversized_upload() -> UploadFile:
    """Larger than settings.max_image_bytes (10MB) — doesn't need to be a
    valid image, since the size cap must trip before any decode is attempted."""
    data = b"\xff\xd8\xff" + b"\x00" * (11 * 1024 * 1024)
    return _upload(data, "huge.jpg")


@pytest.fixture
def fake_exe_upload() -> UploadFile:
    """A PE-header stub renamed to .jpg — must be rejected by the magic-byte
    check regardless of the filename extension."""
    data = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 100
    return _upload(data, "totally_a_photo.jpg")


@pytest.fixture
def exif_gps_jpeg_upload() -> UploadFile:
    """A real JPEG with a fabricated EXIF GPS tag — Pillow can write EXIF
    natively (Image.Exif() + save(..., exif=...)), no extra dependency needed."""
    img = Image.new("RGB", (20, 20), color="green")
    exif = img.getexif()
    gps_ifd = exif.get_ifd(0x8825)  # GPSInfo IFD
    gps_ifd[1] = "N"                  # GPSLatitudeRef
    gps_ifd[2] = (40.0, 44.0, 54.0)   # GPSLatitude (deg, min, sec)
    exif[0x8825] = gps_ifd
    exif[0x0110] = "TestCameraModel"  # Model tag, as an extra metadata proxy
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return _upload(buf.getvalue(), "vacation.jpg")


@pytest.fixture
def oversized_dimension_upload() -> UploadFile:
    """8001x10 — cheap (80,010 pixels) but trips the explicit >8000px-per-side
    rule without needing an actual multi-hundred-MB decompression bomb."""
    buf = io.BytesIO()
    Image.new("RGB", (8001, 10), color="red").save(buf, format="PNG")
    return _upload(buf.getvalue(), "wide.png")
