"""Google Books API service.

Provides search and ISBN lookup against the Google Books Volumes API.
No API key is required for basic read-only access (rate limits apply).
"""

import requests

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
REQUEST_TIMEOUT = 8  # seconds

LANGUAGE_NAMES = {
    "ar": "Arabic",
    "bn": "Bengali",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "gu": "Gujarati",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "pa": "Punjabi",
    "pt": "Portuguese",
    "ru": "Russian",
    "ta": "Tamil",
    "te": "Telugu",
    "ur": "Urdu",
}


class GoogleBooksError(Exception):
    """Raised when the Google Books API call fails."""


def search(query, max_results=8):
    """Search by title, author, or free text.

    Returns a list of book dicts (empty list on no results).
    Raises ``GoogleBooksError`` on network / API failure.
    """
    try:
        resp = requests.get(
            GOOGLE_BOOKS_URL,
            params={"q": query, "maxResults": max_results},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 429:
            raise GoogleBooksError("Rate limited — please try again in a moment")
        resp.raise_for_status()
        items = resp.json().get("items") or []
        return [_volume_to_dict(item) for item in items if item.get("volumeInfo")]
    except requests.Timeout:
        raise GoogleBooksError("Request timed out")
    except requests.RequestException as exc:
        raise GoogleBooksError(f"Network error: {exc}") from exc


def fetch_isbn(isbn):
    """Fetch metadata for a single ISBN.

    Returns a book dict, or ``None`` if no match found.
    Raises ``GoogleBooksError`` on failure.
    """
    requested = _normalize_isbn(isbn)
    results = search(f"isbn:{requested}", max_results=5)
    for result in results:
        identifiers = {
            _normalize_isbn(result.get("isbn")),
            _normalize_isbn(result.get("isbn_10")),
            _normalize_isbn(result.get("isbn_13")),
        }
        if requested in identifiers:
            return result
    return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _volume_to_dict(item):
    """Convert a Google Books volume item into a normalised metadata dict."""
    info = item.get("volumeInfo", {})
    idents = {
        i.get("type"): i.get("identifier")
        for i in info.get("industryIdentifiers") or []
    }
    images = info.get("imageLinks") or {}

    # Prefer larger cover images; force HTTPS
    cover = (
        images.get("large")
        or images.get("medium")
        or images.get("thumbnail")
        or images.get("smallThumbnail")
        or ""
    )
    if cover:
        cover = cover.replace("http://", "https://")
        # Remove the zoom=5 (tiny thumbnail) param if present
        cover = cover.replace("zoom=5", "zoom=1")

    isbn_13 = idents.get("ISBN_13", "")
    isbn_10 = idents.get("ISBN_10", "")

    description = info.get("description", "")
    if isinstance(description, dict):
        description = description.get("value", "")

    return {
        "source": "google_books",
        "title": info.get("title", ""),
        "subtitle": info.get("subtitle", ""),
        "author": ", ".join(info.get("authors") or []),
        "isbn": isbn_13 or isbn_10,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "description": description or "",
        "publisher": info.get("publisher", ""),
        "published_date": info.get("publishedDate", ""),
        "pages": info.get("pageCount"),
        "categories": (info.get("categories") or [])[:5],
        "cover_image": cover,
        "language": _language_name(info.get("language")),
        "preview_link": info.get("previewLink", ""),
    }


def _language_name(value):
    code = str(value or "").strip().lower()
    return LANGUAGE_NAMES.get(code, code.upper() if code else "")


def _normalize_isbn(value):
    return "".join(character for character in str(value or "").upper() if character.isalnum())
