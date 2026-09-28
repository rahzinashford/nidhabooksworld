"""Cover image download service.

Downloads book cover images from external URLs and stores them locally
under ``static/images/covers/downloaded/`` so the app never hotlinks.
Falls back gracefully if the download fails for any reason.
"""

import hashlib
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 8  # seconds
# Only save images with a sane Content-Type
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def download_cover(url, identifier=""):
    """Download *url* and save it locally. Return the relative static path.

    Parameters
    ----------
    url:
        Full https:// URL of the cover image.
    identifier:
        ISBN or sanitised title used to build a stable filename.
        Falls back to a SHA-1 of the URL if empty.

    Returns
    -------
    str or None
        Relative path suitable for ``cover_image`` storage, e.g.
        ``images/covers/downloaded/9780143127550.jpg``.
        Returns ``None`` if the download fails (caller should fall back
        to the original URL or a placeholder).
    """
    if not url or not url.startswith("http"):
        return None

    dest_dir = _ensure_dir()
    filename = _build_filename(url, identifier)
    dest_path = os.path.join(dest_dir, filename)
    relative_path = f"images/covers/downloaded/{filename}"

    # Skip download if already cached on disk
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return relative_path

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "NidhaBooksWorld/1.0 (book cover importer)"},
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            logger.warning("Skipping cover download — unexpected content-type %s for %s", content_type, url)
            return None

        # Read up to MAX_SIZE_BYTES; reject oversized images
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192):
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_SIZE_BYTES:
                logger.warning("Cover image too large (>%d bytes): %s", MAX_SIZE_BYTES, url)
                return None

        payload = b"".join(chunks)
        if not _looks_like_image(payload):
            logger.warning("Skipping cover download — response is not a supported image: %s", url)
            return None

        with open(dest_path, "wb") as f:
            f.write(payload)

        return relative_path

    except requests.Timeout:
        logger.warning("Timeout downloading cover: %s", url)
        return None
    except requests.RequestException as exc:
        logger.warning("Failed to download cover %s: %s", url, exc)
        return None
    except OSError as exc:
        logger.error("Could not write cover to %s: %s", dest_path, exc)
        return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _ensure_dir():
    """Return the absolute path to the download directory, creating it if needed."""
    # Resolve relative to this file: services/ -> app/ -> static/images/covers/downloaded/
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dest_dir = os.path.join(base, "static", "images", "covers", "downloaded")
    os.makedirs(dest_dir, exist_ok=True)
    return dest_dir


def _build_filename(url, identifier):
    """Build a stable filename for the downloaded image."""
    # Sanitise identifier: keep only alphanumerics and hyphens
    if identifier:
        safe = re.sub(r"[^a-zA-Z0-9-]", "", identifier.replace(" ", "-"))[:60]
    else:
        safe = ""

    if not safe:
        safe = hashlib.sha1(url.encode()).hexdigest()[:16]

    # Detect extension from URL or default to .jpg
    ext = ".jpg"
    url_path = url.split("?")[0].lower()
    for candidate in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if url_path.endswith(candidate):
            ext = candidate if candidate != ".jpeg" else ".jpg"
            break

    return f"{safe}{ext}"


def _looks_like_image(payload):
    """Reject HTML/error bodies returned with an image content type."""
    return (
        payload.startswith(b"\xff\xd8\xff")  # JPEG
        or payload.startswith(b"\x89PNG\r\n\x1a\n")  # PNG
        or payload.startswith((b"GIF87a", b"GIF89a"))  # GIF
        or payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"  # WebP
    )
