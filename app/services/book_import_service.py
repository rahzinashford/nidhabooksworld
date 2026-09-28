"""Book import orchestration service.

Coordinates several free public catalogs to return the richest
possible metadata for a search query or ISBN. Handles caching, source
merging, and duplicate detection against the local database.

Source priority
---------------
1. Google Books — broad catalog source and covers
2. Open Library — edition lookup and covers
3. Library of Congress — authoritative bibliographic fields
4. HathiTrust — exact-ISBN bibliographic fallback
5. DC Bookstore — Indian catalog with rich product metadata

For ISBN lookups every source that succeeds contributes to one merged
record: the higher-priority source's fields win but blanks are filled from
lower-priority sources.

For free-text searches only the first source with results is used so we
don't risk mixing candidates from different books.
"""

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta

from app import db
from app.models import Book, ImportCache
from app.services import (
    google_books_service,
    dcbookstore_service,
    hathitrust_service,
    library_of_congress_service,
    openlibrary_service,
)

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(days=30)
CACHE_NAMESPACE = "book-metadata-v3"

# Ordered list of (name, isbn_fn, search_fn) tuples. Adding a new provider
# means appending one entry here — nothing else changes.
SOURCES = [
    ("google_books", google_books_service.fetch_isbn, google_books_service.search),
    ("open_library", openlibrary_service.fetch_isbn, openlibrary_service.search),
    ("library_of_congress", library_of_congress_service.fetch_isbn, library_of_congress_service.search),
    ("hathitrust", hathitrust_service.fetch_isbn, hathitrust_service.search),
    ("dc_bookstore", dcbookstore_service.fetch_isbn, dcbookstore_service.search),
]
SOURCE_NAMES = {"all", *(name for name, _isbn_fn, _search_fn in SOURCES)}

# Metadata fields that participate in merging.
_MERGE_FIELDS = [
    "title", "subtitle", "author", "isbn", "isbn_13", "isbn_10",
    "description", "publisher", "published_date", "pages",
    "categories", "cover_image", "language", "preview_link",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search(query, source="all"):
    """Search by title, author, or free text.

    Returns ``(results, source_name, errors)`` where *results* is a list of
    book dicts and *source_name* is which API supplied them (or None).
    *errors* is a list of ``(source_name, message)`` tuples for sources that
    failed or returned no results.
    """
    query = (query or "").strip()
    if not query:
        return [], None, []

    providers = _providers_for(source)
    cache_key = f"{CACHE_NAMESPACE}:query:{source}:{query.lower()}"
    cached = _get_cached(cache_key)
    if cached is not None:
        sources = cached.get("sources") or []
        return cached["result"], source, []

    errors = []
    all_results = []
    seen = set()
    successful_sources = []
    for name, _isbn_fn, search_fn in providers:
        try:
            results = search_fn(query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Search error from %s: %s", name, exc)
            errors.append((name, str(exc)))
            continue

        if not looks_like_isbn(query):
            results = [result for result in results if _search_result_is_relevant(result, query)]

        if results and source != "all":
            _set_cached(cache_key, results, [name])
            return results, name, errors

        if results:
            successful_sources.append(name)
            for result in results:
                key = _result_key(result)
                if key in seen:
                    continue
                seen.add(key)
                all_results.append(result)
            continue

        errors.append((name, "no results"))

    if all_results:
        _set_cached(cache_key, all_results, successful_sources)
        return all_results, "all", errors
    return [], None, errors


def lookup_isbn(isbn, source="all"):
    """Merge metadata for one ISBN from all sources or one selected source.

    Returns ``(metadata, sources_used, errors)``.  *metadata* is ``None``
    if no source returned a match.
    """
    isbn = _normalize_isbn(isbn)
    providers = _providers_for(source)
    cache_key = f"{CACHE_NAMESPACE}:isbn:{source}:{isbn}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached["result"], cached.get("sources", []), []

    merged = {}
    sources_used = []
    errors = []

    for name, isbn_fn, _search_fn in providers:
        try:
            candidate = isbn_fn(isbn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ISBN lookup error from %s: %s", name, exc)
            errors.append((name, str(exc)))
            continue

        if not candidate:
            errors.append((name, "no match"))
            continue
        if not _candidate_matches_isbn(candidate, isbn):
            errors.append((name, "ISBN mismatch"))
            continue

        sources_used.append(name)
        merged = _merge(merged, candidate)

    if not merged.get("title"):
        return None, sources_used, errors

    merged.setdefault("isbn", isbn)
    _set_cached(cache_key, merged, sources_used)
    return merged, sources_used, errors


def _providers_for(source):
    source = source or "all"
    if source == "all":
        return SOURCES
    if source not in SOURCE_NAMES:
        raise ValueError(f"Unknown metadata source: {source}")
    return [entry for entry in SOURCES if entry[0] == source]


def _result_key(result):
    isbn = _normalize_isbn(result.get("isbn"))
    if isbn:
        return f"isbn:{isbn}"
    title = (result.get("title") or "").strip().lower()
    author = (result.get("author") or "").strip().lower()
    return f"title:{title}|author:{author}"


def _candidate_matches_isbn(candidate, requested_isbn):
    """Reject a provider response that identifies a different edition."""
    identifiers = {
        _normalize_isbn(candidate.get("isbn")),
        _normalize_isbn(candidate.get("isbn_10")),
        _normalize_isbn(candidate.get("isbn_13")),
    }
    identifiers.discard("")
    return not identifiers or requested_isbn in identifiers


def _search_result_is_relevant(result, query):
    """Keep provider search results tied to the requested title or author."""
    haystack = " ".join(
        str(result.get(field) or "").casefold()
        for field in ("title", "subtitle", "author", "alternate_titles")
    )
    if not haystack.strip():
        return False

    query_text = str(query or "").strip().casefold()
    if query_text and query_text in haystack:
        return True

    terms = [term for term in _search_terms(query_text) if len(term) > 1]
    if not terms:
        return True

    matches = sum(term in haystack for term in terms)
    required = len(terms) if len(terms) <= 2 else max(1, (len(terms) + 1) // 2)
    return matches >= required


def _search_terms(value):
    """Split on punctuation while keeping Indic combining marks with letters."""
    terms = []
    current = []
    for character in value:
        category = unicodedata.category(character)
        if category[0] in {"L", "N"} or category[0] == "M":
            current.append(character)
        elif current:
            terms.append("".join(current))
            current = []
    if current:
        terms.append("".join(current))
    return terms


def find_duplicate(isbn, title, author):
    """Check whether a book already exists in the local database.

    Checks by ISBN first (exact match), then by normalised title + author.
    Returns the duplicate ``Book`` instance or ``None``.
    """
    isbn = (isbn or "").strip()
    title = (title or "").strip()
    author = (author or "").strip()

    if isbn:
        existing = Book.query.filter_by(isbn=isbn).first()
        if existing:
            return existing

    if title and author:
        existing = Book.query.filter(
            db.func.lower(Book.title) == title.lower(),
            db.func.lower(Book.author) == author.lower(),
        ).first()
        if existing:
            return existing

    return None


def looks_like_isbn(value):
    """True if *value* looks like an ISBN-10 or ISBN-13."""
    import re
    cleaned = re.sub(r"[\s-]", "", value or "")
    return bool(re.fullmatch(r"\d{9}[\dXx]|\d{13}", cleaned))


# ---------------------------------------------------------------------------
# Caching helpers
# ---------------------------------------------------------------------------


def _get_cached(key):
    row = ImportCache.query.get(key)
    if row is None:
        return None
    if datetime.utcnow() - row.fetched_at > CACHE_TTL:
        return None
    return json.loads(row.payload)


def _set_cached(key, result, sources):
    payload = json.dumps({"result": result, "sources": sources})
    source_label = ",".join(sources) if sources else ""
    row = ImportCache.query.get(key)
    if row is None:
        row = ImportCache(key=key, payload=payload, source=source_label, fetched_at=datetime.utcnow())
        db.session.add(row)
    else:
        row.payload = payload
        row.source = source_label
        row.fetched_at = datetime.utcnow()
    db.session.commit()


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------


def _merge(base, candidate):
    """Fill blank fields in *base* from *candidate*; filled fields are kept."""
    merged = dict(base)
    for field in _MERGE_FIELDS:
        value = candidate.get(field)
        existing = merged.get(field)
        empty_existing = existing in (None, "", [])
        empty_value = value in (None, "", [])
        if empty_existing and not empty_value:
            merged[field] = value
    return merged


def _normalize_isbn(value):
    import re
    return re.sub(r"[\s-]", "", value or "").upper()
