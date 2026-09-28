"""HathiTrust bibliographic metadata service.

HathiTrust exposes a public, no-key bibliographic API for exact identifiers.
It is intentionally used only for ISBN lookups: its bibliographic API is not
a general title-search API, and limiting it to exact ISBN calls keeps matches
precise.
"""

import re

import requests

BASE_URL = "https://catalog.hathitrust.org/api/volumes/brief/isbn"
REQUEST_TIMEOUT = 12

LANGUAGE_NAMES = {
    "eng": "English",
    "hin": "Hindi",
    "mal": "Malayalam",
    "tam": "Tamil",
    "tel": "Telugu",
    "kan": "Kannada",
    "mar": "Marathi",
    "ben": "Bengali",
    "guj": "Gujarati",
    "pan": "Punjabi",
    "urd": "Urdu",
    "san": "Sanskrit",
}


class HathiTrustError(Exception):
    """Raised when HathiTrust cannot complete a request."""


def search(query, max_results=8):
    """Search by ISBN only; HathiTrust does not provide keyword search here."""
    query = (query or "").strip()
    if not _looks_like_isbn(query):
        return []
    result = fetch_isbn(query)
    return [result] if result else []


def fetch_isbn(isbn):
    """Fetch a bibliographic record for one ISBN."""
    isbn = _normalize_isbn(isbn)
    try:
        response = requests.get(
            f"{BASE_URL}/{isbn}.json",
            headers={"User-Agent": "NidhaBooksWorld/1.0 metadata importer"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise HathiTrustError("HathiTrust request timed out") from exc
    except requests.RequestException as exc:
        raise HathiTrustError(f"HathiTrust network error: {exc}") from exc
    except ValueError as exc:
        raise HathiTrustError("HathiTrust returned invalid JSON") from exc

    records = payload.get("records") or {}
    if isinstance(records, list):
        record_values = records
    elif isinstance(records, dict):
        record_values = list(records.values())
    else:
        record_values = []

    for record in record_values:
        if not isinstance(record, dict):
            continue
        result = _record_to_dict(record, isbn)
        identifiers = _identifier_values(record)
        if identifiers and isbn not in identifiers:
            continue
        if result.get("title"):
            return result
    return None


def _record_to_dict(record, requested_isbn):
    isbn_values = _as_list(record.get("isbns") or record.get("isbn"))
    normalized_isbns = [_normalize_isbn(value) for value in isbn_values]
    isbn_13 = next((value for value in normalized_isbns if len(value) == 13), "")
    isbn_10 = next((value for value in normalized_isbns if len(value) == 10), "")

    return {
        "source": "hathitrust",
        "title": _first_text(record.get("titles") or record.get("title")),
        "subtitle": "",
        "author": _join_values(record.get("authors") or record.get("author")),
        "isbn": isbn_13 or isbn_10 or requested_isbn,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "description": _first_text(record.get("descriptions") or record.get("description")),
        "publisher": _first_text(record.get("publishers") or record.get("publisher")),
        "published_date": _first_text(
            record.get("publicationDates")
            or record.get("publication_dates")
            or record.get("date")
        ),
        "pages": _first_int(record.get("pages") or record.get("pageCount")),
        "categories": _as_list(record.get("subjects") or record.get("subject"))[:5],
        "cover_image": (
            f"https://covers.openlibrary.org/b/isbn/{requested_isbn}-L.jpg?default=false"
        ),
        "language": _join_languages(record.get("languages") or record.get("language")),
        "preview_link": record.get("recordURL") or "",
    }


def _identifier_values(record):
    values = _as_list(record.get("isbns") or record.get("isbn"))
    return {_normalize_isbn(value) for value in values if _normalize_isbn(value)}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def _first_text(value):
    values = _as_list(value)
    for item in values:
        if isinstance(item, dict):
            item = item.get("value") or item.get("name") or item.get("text")
        if item not in (None, ""):
            return str(item).strip()
    return ""


def _join_values(value):
    values = []
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("name") or item.get("value") or item.get("text")
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return ", ".join(values)


def _join_languages(value):
    values = []
    for item in _as_list(value):
        code = str(item or "").strip().lower()[:3]
        language = LANGUAGE_NAMES.get(code, code.upper() if code else "")
        if language and language not in values:
            values.append(language)
    return ", ".join(values)


def _first_int(value):
    text = _first_text(value)
    match = re.search(r"\d[\d,]*", text)
    return int(match.group(0).replace(",", "")) if match else None


def _normalize_isbn(value):
    return re.sub(r"[\s-]", "", str(value or "")).upper()


def _looks_like_isbn(value):
    cleaned = _normalize_isbn(value)
    return bool(re.fullmatch(r"\d{9}[\dX]|\d{13}", cleaned))