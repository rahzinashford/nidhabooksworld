"""DC Books catalog service.

DC Bookstore's public product pages are rendered by a client-side app. The
app uses a public JSON endpoint for those pages, so consuming that endpoint is
more reliable than scraping the empty HTML shell and gives us the same
metadata shown in the site's ``book-info-card``.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor

import requests

API_BASE = "https://dcbookstore.com/dc-admin/api/v1"
SITE_BASE = "https://dcbookstore.com"
REQUEST_TIMEOUT = 8
DEFAULT_MAX_RESULTS = 8


class DCBookstoreError(Exception):
    """Raised when the DC Bookstore catalog cannot be queried."""


def search(query, max_results=DEFAULT_MAX_RESULTS):
    """Search DC Books and hydrate each result with its full product record."""
    try:
        response = requests.get(
            f"{API_BASE}/search",
            params={
                "keyword": query,
                "category": "all",
                "per_page": min(max(int(max_results), 1), 16),
                "page": 1,
            },
            headers={"Accept": "application/json", "User-Agent": "NidhaBooksWorld/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 429:
            raise DCBookstoreError("Rate limited — please try again in a moment")
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise DCBookstoreError("Request timed out") from exc
    except requests.RequestException as exc:
        raise DCBookstoreError(f"Network error: {exc}") from exc
    except ValueError as exc:
        raise DCBookstoreError("DC Bookstore returned invalid JSON") from exc

    rows = payload.get("data") or []
    # Combo offers represent multiple products, not a single catalog book.
    rows = [
        row for row in rows
        if str(row.get("product_type") or "Book").casefold() == "book"
        and "combo offer" not in str(row.get("title") or "").casefold()
    ]

    # Product details are independent requests. Hydrating in parallel keeps
    # the admin search responsive without issuing an unbounded number of calls.
    with ThreadPoolExecutor(max_workers=min(4, max(len(rows), 1))) as executor:
        results = list(executor.map(_hydrate_search_row, rows[:max_results]))
    return [result for result in results if result and result.get("title")]


def fetch_isbn(isbn):
    """Find and hydrate the DC Books record for an exact ISBN."""
    requested = _normalize_isbn(isbn)
    if not requested:
        return None

    for result in search(requested, max_results=5):
        identifiers = {
            _normalize_isbn(result.get("isbn")),
            _normalize_isbn(result.get("isbn_10")),
            _normalize_isbn(result.get("isbn_13")),
        }
        identifiers.discard("")
        if requested in identifiers:
            return result
    return None


def _hydrate_search_row(row):
    basic = _search_row_to_dict(row)
    slug = str(row.get("sefurl") or "").strip()
    if not slug:
        return basic

    try:
        response = requests.get(
            f"{API_BASE}/products/{requests.utils.quote(slug, safe='')}",
            headers={"Accept": "application/json", "User-Agent": "NidhaBooksWorld/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            return basic
        response.raise_for_status()
        payload = response.json()
        detail = payload.get("data") if payload.get("status", True) else None
        if not detail:
            return basic
    except (requests.RequestException, ValueError):
        # A search result is still useful if one detail request is unavailable.
        return basic

    hydrated = dict(basic)
    hydrated.update(_product_to_dict(detail))
    return hydrated


def _search_row_to_dict(row):
    authors = row.get("authors") or []
    author_names = [
        author.get("name", "") if isinstance(author, dict) else str(author)
        for author in authors
    ]
    return {
        "source": "dc_bookstore",
        "source_url": _site_url(row.get("sefurl")),
        "title": row.get("title", ""),
        "subtitle": "",
        "author": ", ".join(name for name in author_names if name),
        "isbn": "",
        "isbn_13": "",
        "isbn_10": "",
        "description": "",
        "publisher": "",
        "published_date": "",
        "pages": None,
        "categories": [],
        "cover_image": row.get("image") or "",
        "language": row.get("language") or "",
        "preview_link": _site_url(row.get("sefurl")),
    }


def _product_to_dict(product):
    isbn = _normalize_isbn(product.get("isbn"))
    authors = product.get("authors") or []
    author_names = [
        author.get("name", "") if isinstance(author, dict) else str(author)
        for author in authors
    ]
    categories = product.get("categories") or []
    category_names = [
        category.get("name", "") if isinstance(category, dict) else str(category)
        for category in categories
    ]
    publisher = product.get("publisher") or {}
    if isinstance(publisher, dict):
        publisher = publisher.get("name", "")

    slug = product.get("sefurl")
    return {
        "source": "dc_bookstore",
        "source_url": _site_url(slug),
        "title": product.get("title") or "",
        "subtitle": "",
        "author": ", ".join(name for name in author_names if name),
        "isbn": isbn,
        "isbn_13": isbn if len(isbn) == 13 else "",
        "isbn_10": isbn if len(isbn) == 10 else "",
        "description": _clean_html(product.get("summary") or product.get("description")),
        "publisher": publisher,
        "published_date": product.get("publishing_date") or "",
        "pages": product.get("pages"),
        "categories": [name for name in category_names if name][:5],
        "cover_image": product.get("image") or "",
        "language": product.get("language") or "",
        "preview_link": _site_url(slug),
    }


def _site_url(slug):
    slug = str(slug or "").strip()
    return f"{SITE_BASE}/books/{slug}" if slug else ""


def _clean_html(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _normalize_isbn(value):
    return "".join(character for character in str(value or "").upper() if character.isalnum())