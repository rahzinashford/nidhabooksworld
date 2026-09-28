"""Library of Congress MARC metadata service.

The Library of Congress SRU catalog is public and requires no API key. It is
used as a lower-priority bibliographic source because its records are strong
for publisher, pagination, language, and identifier data, while its coverage
of modern retail covers and descriptions is less consistent than Google Books
or Open Library.
"""

import re
import xml.etree.ElementTree as ET

import requests

SRU_URL = "http://lx2.loc.gov:210/lcdb"
REQUEST_TIMEOUT = 12

SRW_NS = "http://www.loc.gov/zing/srw/"
DIAGNOSTIC_NS = "http://www.loc.gov/zing/srw/diagnostic/"
MARC_NS = "http://www.loc.gov/MARC21/slim"

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
    "fra": "French",
    "deu": "German",
    "spa": "Spanish",
}


class LibraryOfCongressError(Exception):
    """Raised when the Library of Congress catalog cannot be queried."""


def search(query, max_results=8):
    """Search the catalog by title or creator.

    ISBN queries are routed through the exact ISBN lookup so a selected
    result can never be a nearby title with a similar name.
    """
    query = (query or "").strip()
    if not query:
        return []
    if _looks_like_isbn(query):
        result = fetch_isbn(query)
        return [result] if result else []

    term = _cql_term(query)
    for cql in (f"dc.title={term}", f"dc.creator={term}"):
        records = _request(cql, max_results)
        results = [_record_to_dict(record) for record in records]
        results = [result for result in results if result.get("title")]
        if results:
            return results
    return []


def fetch_isbn(isbn):
    """Fetch one catalog record whose ISBN exactly matches *isbn*."""
    isbn = _normalize_isbn(isbn)
    records = _request(f"bath.isbn={isbn}", 4)
    for record in records:
        result = _record_to_dict(record)
        if isbn in _record_isbn_values(record):
            return result
    return None


def _request(query, max_results):
    try:
        response = requests.get(
            SRU_URL,
            params={
                "version": "1.1",
                "operation": "searchRetrieve",
                "query": query,
                "maximumRecords": max_results,
                "recordSchema": "marcxml",
            },
            headers={"User-Agent": "NidhaBooksWorld/1.0 metadata importer"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except requests.Timeout as exc:
        raise LibraryOfCongressError("Library of Congress request timed out") from exc
    except requests.RequestException as exc:
        raise LibraryOfCongressError(f"Library of Congress network error: {exc}") from exc
    except ET.ParseError as exc:
        raise LibraryOfCongressError("Library of Congress returned invalid XML") from exc

    diagnostic = root.find(f".//{{{DIAGNOSTIC_NS}}}diagnostic")
    if diagnostic is not None:
        message = diagnostic.findtext(f"{{{SRW_NS}}}message") or "catalog query failed"
        raise LibraryOfCongressError(f"Library of Congress: {message}")

    return root.findall(f".//{{{SRW_NS}}}recordData/{{{MARC_NS}}}record")


def _record_to_dict(record):
    isbn_values = _field_values(record, "020", "a")
    normalized_isbns = [_normalize_isbn(value) for value in isbn_values]
    isbn_13 = next((value for value in normalized_isbns if len(value) == 13), "")
    isbn_10 = next((value for value in normalized_isbns if len(value) == 10), "")
    primary_isbn = isbn_13 or isbn_10

    primary_title = _clean_text(
        _field_values(record, "245", "a")[0] if _field_values(record, "245", "a") else ""
    )
    alternate_titles = _title_variants(record, "246")
    title = alternate_titles[0] if alternate_titles else primary_title
    subtitle = _clean_title(
        _field_values(record, "245", "b")[0] if _field_values(record, "245", "b") else ""
    )
    authors = _unique(
        _field_values(record, "100", "a")
        + _field_values(record, "110", "a")
        + _field_values(record, "700", "a")
    )
    publishers = _field_values(record, "264", "b") or _field_values(record, "260", "b")
    dates = _field_values(record, "264", "c") or _field_values(record, "260", "c")
    descriptions = _field_values(record, "520", "a")
    languages = _field_values(record, "041", "a")
    if not languages:
        leader = record.findtext(f"{{{MARC_NS}}}controlfield[@tag='008']") or ""
        if len(leader) >= 38:
            languages = [leader[35:38]]

    return {
        "source": "library_of_congress",
        "title": title,
        "subtitle": subtitle,
        "alternate_titles": [primary_title] + alternate_titles if primary_title else alternate_titles,
        "author": ", ".join(_author_name(value) for value in authors),
        "isbn": primary_isbn,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "description": _clean_text(descriptions[0]) if descriptions else "",
        "publisher": _clean_text(publishers[0]) if publishers else "",
        "published_date": _clean_text(dates[0]) if dates else "",
        "pages": _pages_from_extent(_field_values(record, "300", "a")),
        "categories": [_clean_text(value) for value in _field_values(record, "650", "a")[:5]],
        "cover_image": (
            f"https://covers.openlibrary.org/b/isbn/{primary_isbn}-L.jpg?default=false"
            if primary_isbn
            else ""
        ),
        "language": ", ".join(_language_name(value) for value in languages if value),
        "preview_link": (
            f"https://www.loc.gov/books/?q={primary_isbn}"
            if primary_isbn
            else ""
        ),
    }


def _field_values(record, tag, code):
    return [
        (subfield.text or "").strip()
        for subfield in record.findall(
            f".//{{{MARC_NS}}}datafield[@tag='{tag}']/{{{MARC_NS}}}subfield[@code='{code}']"
        )
        if (subfield.text or "").strip()
    ]


def _record_isbn_values(record):
    return {
        _normalize_isbn(value)
        for value in _field_values(record, "020", "a")
        if _normalize_isbn(value)
    }


def _title_variants(record, tag):
    variants = []
    for field in record.findall(f".//{{{MARC_NS}}}datafield[@tag='{tag}']"):
        parts = [
            (subfield.text or "").strip()
            for subfield in field.findall(f"{{{MARC_NS}}}subfield")
            if (subfield.text or "").strip()
        ]
        title = _clean_title(" ".join(parts))
        if title and title.casefold() not in {value.casefold() for value in variants}:
            variants.append(title)
    return variants


def _pages_from_extent(extents):
    for extent in extents:
        match = re.search(r"([\d,]+)\s*(?:p\.|pages?)", extent, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
        match = re.search(r"\d[\d,]*", extent)
        if match:
            return int(match.group(0).replace(",", ""))
    return None


def _language_name(value):
    code = str(value or "").strip().lower()[:3]
    return LANGUAGE_NAMES.get(code, code.upper() if code else "")


def _cql_term(value):
    escaped = re.sub(r'(["\\])', r"\\\1", value)
    return f'"{escaped}"'


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip(" /:;,.")


def _clean_title(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip(" /:;,. -")
    value = re.sub(r"\s*([:/])\s*", " - ", value)
    value = re.sub(r"\s*-\s*", " - ", value)
    value = re.sub(r"(?:\s*-\s*){2,}", " - ", value)
    return re.sub(r"\s+", " ", value).strip(" -")


def _author_name(value):
    value = _clean_text(value).rstrip(".")
    if "," not in value:
        return value
    family, given = (part.strip() for part in value.split(",", 1))
    return f"{given} {family}".strip()


def _unique(values):
    seen = set()
    result = []
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _normalize_isbn(value):
    return re.sub(r"[\s-]", "", str(value or "")).upper()


def _looks_like_isbn(value):
    cleaned = _normalize_isbn(value)
    return bool(re.fullmatch(r"\d{9}[\dX]|\d{13}", cleaned))