"""Book metadata import service.

Looks up catalog metadata for a book from external sources so an admin
never has to type out title/author/description/etc. by hand -- they only
ever supply the store-specific bits (price, stock, condition).

Sources are tried in priority order; if one fails (network error, rate
limit, no match) the next one is tried automatically:

1. Google Books API   -- no key required for basic search.
2. Open Library API   -- no key required.
3. Library of Congress SRU -- no key required.
4. HathiTrust -- public exact-ISBN lookup, no key required.

For an ISBN lookup, every source that succeeds contributes to one merged
result: the highest-priority source's fields win, but any field it left
blank (e.g. no description) is filled in from a lower-priority source that
has it. That merged dict is what gets cached and returned.

For a free-text (title/author) search, sources are tried until one returns
a non-empty candidate list -- merging candidate lists across sources would
risk mixing up different books, so the first source with results wins and
the admin picks the right candidate from that list.
"""

import json
import re
from datetime import datetime, timedelta

import requests

from app import db
from app.models import ImportCache
from app.services import hathitrust_service, library_of_congress_service

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPEN_LIBRARY_ISBN_URL = "https://openlibrary.org/isbn/{isbn}.json"
OPEN_LIBRARY_AUTHOR_URL = "https://openlibrary.org{key}.json"
OPEN_LIBRARY_COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

REQUEST_TIMEOUT = 6  # seconds
CACHE_TTL = timedelta(days=30)

METADATA_FIELDS = [
    "title",
    "author",
    "isbn",
    "description",
    "publisher",
    "pages",
    "categories",
    "cover_image",
    "language",
]


class ImportSourceError(Exception):
    """A single source failed (network, rate limit, no match) -- try the next one."""


# --- Public API -------------------------------------------------------------


def looks_like_isbn(value):
    """True if ``value`` is plausibly an ISBN-10 or ISBN-13 (spaces/hyphens ok)."""
    cleaned = re.sub(r"[\s-]", "", value or "")
    return bool(re.fullmatch(r"\d{9}[\dXx]|\d{13}", cleaned))


def normalize_isbn(value):
    return re.sub(r"[\s-]", "", value or "").upper()


def lookup_isbn(isbn):
    """Merge metadata for one ISBN across sources. Returns (result, sources_used, errors)."""
    isbn = normalize_isbn(isbn)
    key = f"isbn:{isbn}"
    cached = _get_cached(key)
    if cached is not None:
        return cached["result"], cached["sources"], []

    merged = {}
    sources_used = []
    errors = []
    for name, fetch_isbn, _fetch_query in SOURCES:
        try:
            candidate = fetch_isbn(isbn)
        except Exception as exc:  # noqa: BLE001 -- any source failure just falls through
            errors.append((name, str(exc)))
            continue
        if not candidate:
            errors.append((name, "no match"))
            continue
        sources_used.append(name)
        merged = merge_fields(merged, candidate)

    if not merged.get("title"):
        return None, sources_used, errors

    merged.setdefault("isbn", isbn)
    _set_cached(key, {"result": merged, "sources": sources_used})
    return merged, sources_used, errors


def search_query(query):
    """Search by title/author text. Returns (candidates, source_used, errors).

    Unlike ``lookup_isbn``, this does NOT merge across sources -- the first
    source with results wins, and the admin picks the right candidate.
    """
    query = (query or "").strip()
    key = f"query:{query.lower()}"
    cached = _get_cached(key)
    if cached is not None:
        return cached["result"], cached["sources"][0] if cached["sources"] else None, []

    errors = []
    for name, _fetch_isbn, fetch_query in SOURCES:
        try:
            candidates = fetch_query(query)
        except Exception as exc:  # noqa: BLE001
            errors.append((name, str(exc)))
            continue
        if candidates:
            _set_cached(key, {"result": candidates, "sources": [name]})
            return candidates, name, errors
        errors.append((name, "no results"))

    return [], None, errors


# --- Caching ------------------------------------------------------------


def _get_cached(key):
    row = ImportCache.query.get(key)
    if row is None:
        return None
    if datetime.utcnow() - row.fetched_at > CACHE_TTL:
        return None
    data = json.loads(row.payload)
    return {"result": data.get("result"), "sources": data.get("sources", [])}


def _set_cached(key, data):
    row = ImportCache.query.get(key)
    payload = json.dumps({"result": data["result"], "sources": data["sources"]})
    source_label = ",".join(data["sources"]) if data["sources"] else ""
    if row is None:
        row = ImportCache(key=key, payload=payload, source=source_label, fetched_at=datetime.utcnow())
        db.session.add(row)
    else:
        row.payload = payload
        row.source = source_label
        row.fetched_at = datetime.utcnow()
    db.session.commit()


# --- Merge helper ---------------------------------------------------------


def merge_fields(base, candidate):
    """Fill blanks in ``base`` from ``candidate``; never overwrite a filled field."""
    merged = dict(base)
    for field in METADATA_FIELDS:
        value = candidate.get(field)
        existing = merged.get(field)
        empty_existing = existing in (None, "", [])
        empty_value = value in (None, "", [])
        if empty_existing and not empty_value:
            merged[field] = value
    return merged


# --- Google Books ---------------------------------------------------------


def _google_books_isbn(isbn):
    return _first_google_result(f"isbn:{isbn}")


def _google_books_query(query):
    resp = requests.get(
        GOOGLE_BOOKS_URL, params={"q": query, "maxResults": 8}, timeout=REQUEST_TIMEOUT
    )
    if resp.status_code == 429:
        raise ImportSourceError("Google Books: rate limited")
    resp.raise_for_status()
    items = resp.json().get("items") or []
    return [_google_volume_to_dict(item) for item in items if item.get("volumeInfo")]


def _first_google_result(q):
    resp = requests.get(GOOGLE_BOOKS_URL, params={"q": q, "maxResults": 1}, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 429:
        raise ImportSourceError("Google Books: rate limited")
    resp.raise_for_status()
    items = resp.json().get("items") or []
    if not items:
        return None
    return _google_volume_to_dict(items[0])


def _google_volume_to_dict(item):
    info = item.get("volumeInfo", {})
    idents = {i.get("type"): i.get("identifier") for i in info.get("industryIdentifiers", [])}
    images = info.get("imageLinks", {}) or {}
    cover = images.get("thumbnail") or images.get("smallThumbnail") or ""
    return {
        "source": "google_books",
        "title": info.get("title", ""),
        "author": ", ".join(info.get("authors", []) or []),
        "isbn": idents.get("ISBN_13") or idents.get("ISBN_10") or "",
        "description": info.get("description", ""),
        "publisher": info.get("publisher", ""),
        "pages": info.get("pageCount"),
        "categories": (info.get("categories") or [])[:5],
        "cover_image": cover.replace("http://", "https://"),
        "language": (info.get("language") or "").upper(),
    }


# --- Open Library ---------------------------------------------------------


def _open_library_isbn(isbn):
    resp = requests.get(OPEN_LIBRARY_ISBN_URL.format(isbn=isbn), timeout=REQUEST_TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()

    author_refs = list(data.get("authors") or [])

    # Editions often don't carry author info directly -- it lives on the
    # parent "work" record instead (e.g. /works/OL17295077W). Fall back to
    # that when the edition itself has no authors listed.
    subjects = list(data.get("subjects") or [])
    if not author_refs:
        for w in data.get("works") or []:
            work_key = w.get("key")
            if not work_key:
                continue
            try:
                wr = requests.get(OPEN_LIBRARY_AUTHOR_URL.format(key=work_key), timeout=REQUEST_TIMEOUT)
            except requests.RequestException:
                continue
            if not wr.ok:
                continue
            work_data = wr.json()
            author_refs.extend(work_data.get("authors") or [])
            if not subjects:
                subjects = list(work_data.get("subjects") or [])

    author_names = []
    for a in author_refs:
        # Edition-level refs look like {"key": "/authors/OL..."}; work-level
        # refs look like {"author": {"key": "/authors/OL..."}, "type": {...}}.
        author_key = a.get("key") or (a.get("author") or {}).get("key")
        if not author_key:
            continue
        try:
            ar = requests.get(OPEN_LIBRARY_AUTHOR_URL.format(key=author_key), timeout=REQUEST_TIMEOUT)
            if ar.ok:
                name = ar.json().get("name")
                if name:
                    author_names.append(name)
        except requests.RequestException:
            continue

    publishers = data.get("publishers") or []
    return {
        "source": "open_library",
        "title": data.get("title", ""),
        "author": ", ".join(author_names),
        "isbn": isbn,
        "description": _open_library_description(data.get("description")),
        "publisher": publishers[0] if publishers else "",
        "pages": data.get("number_of_pages"),
        "categories": [s for s in subjects if isinstance(s, str)][:5],
        "cover_image": OPEN_LIBRARY_COVER_URL.format(isbn=isbn),
        "language": "",
    }


def _open_library_query(query):
    resp = requests.get(
        OPEN_LIBRARY_SEARCH_URL, params={"q": query, "limit": 8}, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    docs = resp.json().get("docs") or []
    results = []
    for d in docs:
        isbn_list = d.get("isbn") or []
        primary_isbn = isbn_list[0] if isbn_list else ""
        results.append(
            {
                "source": "open_library",
                "title": d.get("title", ""),
                "author": ", ".join(d.get("author_name") or []),
                "isbn": primary_isbn,
                "description": "",
                "publisher": (d.get("publisher") or [""])[0],
                "pages": d.get("number_of_pages_median"),
                "categories": (d.get("subject") or [])[:5],
                "cover_image": OPEN_LIBRARY_COVER_URL.format(isbn=primary_isbn) if primary_isbn else "",
                "language": "",
            }
        )
    return results


def _open_library_description(desc):
    if isinstance(desc, dict):
        return desc.get("value", "")
    return desc or ""


SOURCES = [
    ("google_books", _google_books_isbn, _google_books_query),
    ("open_library", _open_library_isbn, _open_library_query),
    ("library_of_congress", library_of_congress_service.fetch_isbn, library_of_congress_service.search),
    ("hathitrust", hathitrust_service.fetch_isbn, hathitrust_service.search),
]
