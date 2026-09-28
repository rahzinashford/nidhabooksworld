"""Open Library API service.

Provides search and ISBN lookup against the Open Library APIs.
All endpoints are public and require no API key.
"""

import requests

SEARCH_URL = "https://openlibrary.org/search.json"
ISBN_URL = "https://openlibrary.org/isbn/{isbn}.json"
ENTITY_URL = "https://openlibrary.org{key}.json"
COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

REQUEST_TIMEOUT = 8  # seconds

LANGUAGE_NAMES = {
    "ara": "Arabic",
    "ben": "Bengali",
    "deu": "German",
    "eng": "English",
    "fra": "French",
    "guj": "Gujarati",
    "hin": "Hindi",
    "ita": "Italian",
    "jpn": "Japanese",
    "kan": "Kannada",
    "mal": "Malayalam",
    "mar": "Marathi",
    "pan": "Punjabi",
    "por": "Portuguese",
    "rus": "Russian",
    "spa": "Spanish",
    "tam": "Tamil",
    "tel": "Telugu",
    "urd": "Urdu",
}


class OpenLibraryError(Exception):
    """Raised when an Open Library API call fails."""


def search(query, max_results=8):
    """Search by title/author/keyword.

    Returns a list of book dicts (empty list on no results).
    Raises ``OpenLibraryError`` on network / API failure.
    """
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"q": query, "limit": max_results},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        docs = resp.json().get("docs") or []
        return [_doc_to_dict(d) for d in docs]
    except requests.Timeout:
        raise OpenLibraryError("Request timed out")
    except requests.RequestException as exc:
        raise OpenLibraryError(f"Network error: {exc}") from exc


def fetch_isbn(isbn):
    """Fetch full edition metadata for a specific ISBN.

    Returns a book dict, or ``None`` if not found.
    Raises ``OpenLibraryError`` on network failure.
    """
    try:
        resp = requests.get(ISBN_URL.format(isbn=isbn), timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout:
        raise OpenLibraryError("Request timed out")
    except requests.RequestException as exc:
        raise OpenLibraryError(f"Network error: {exc}") from exc

    # -- Resolve authors -------------------------------------------------------
    # Edition records often have no authors field directly; it lives on the
    # parent work. Fall back to the work record when needed.
    author_refs = list(data.get("authors") or [])
    subjects = list(data.get("subjects") or [])

    if not author_refs:
        for w in data.get("works") or []:
            work_key = w.get("key")
            if not work_key:
                continue
            try:
                wr = requests.get(ENTITY_URL.format(key=work_key), timeout=REQUEST_TIMEOUT)
            except requests.RequestException:
                continue
            if not wr.ok:
                continue
            work_data = wr.json()
            author_refs.extend(work_data.get("authors") or [])
            if not subjects:
                subjects = list(work_data.get("subjects") or [])

    author_names = _resolve_author_names(author_refs)

    publishers = data.get("publishers") or []
    published = ""
    if data.get("publish_date"):
        published = data["publish_date"]

    covers = data.get("covers") or []
    cover_image = (
        f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg?default=false"
        if covers
        else COVER_URL.format(isbn=isbn) + "?default=false"
    )

    return {
        "source": "open_library",
        "title": data.get("title", ""),
        "subtitle": data.get("subtitle", ""),
        "author": ", ".join(author_names),
        "isbn": isbn,
        "isbn_13": isbn if len(isbn) == 13 else "",
        "isbn_10": isbn if len(isbn) == 10 else "",
        "description": _extract_description(data.get("description")),
        "publisher": publishers[0] if publishers else "",
        "published_date": published,
        "pages": data.get("number_of_pages"),
        "categories": [s for s in subjects if isinstance(s, str)][:5],
        "cover_image": cover_image,
        "language": _language_name((data.get("languages") or [{}])[0]),
        "preview_link": f"https://openlibrary.org/isbn/{isbn}",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _doc_to_dict(doc):
    """Convert a search result doc to a normalised book dict."""
    isbn_list = doc.get("isbn") or []
    primary_isbn = isbn_list[0] if isbn_list else ""
    year = ""
    if doc.get("first_publish_year"):
        year = str(doc["first_publish_year"])

    cover_id = (doc.get("cover_i") or "")
    cover_image = (
        f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg?default=false"
        if cover_id
        else COVER_URL.format(isbn=primary_isbn) + "?default=false" if primary_isbn else ""
    )

    return {
        "source": "open_library",
        "title": doc.get("title", ""),
        "subtitle": "",
        "author": ", ".join(doc.get("author_name") or []),
        "isbn": primary_isbn,
        "isbn_13": "",
        "isbn_10": "",
        "description": "",
        "publisher": (doc.get("publisher") or [""])[0],
        "published_date": year,
        "pages": doc.get("number_of_pages_median"),
        "categories": (doc.get("subject") or [])[:5],
        "cover_image": cover_image,
        "language": _language_name((doc.get("language") or [""])[0]),
        "preview_link": (
            f"https://openlibrary.org/isbn/{primary_isbn}"
            if primary_isbn
            else ""
        ),
    }


def _resolve_author_names(author_refs):
    """Fetch the name for each author ref from Open Library."""
    names = []
    for a in author_refs:
        # Edition-level: {"key": "/authors/OLxxx"}
        # Work-level: {"author": {"key": "/authors/OLxxx"}, "type": {...}}
        key = a.get("key") or (a.get("author") or {}).get("key")
        if not key:
            continue
        try:
            r = requests.get(ENTITY_URL.format(key=key), timeout=REQUEST_TIMEOUT)
            if r.ok:
                name = r.json().get("name")
                if name:
                    names.append(name)
        except requests.RequestException:
            continue
    return names


def _extract_description(raw):
    """Normalise Open Library's description field (may be a string or dict)."""
    if isinstance(raw, dict):
        return raw.get("value", "")
    return raw or ""


def _language_name(value):
    if isinstance(value, dict):
        value = value.get("key", "")
    code = str(value or "").strip().lower().split("/")[-1]
    return LANGUAGE_NAMES.get(code, code.upper() if code else "")
