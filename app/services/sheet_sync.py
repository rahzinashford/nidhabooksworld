"""Google Sheets-backed catalog synchronization.

The Books worksheet is the authoritative catalog.  The existing SQLAlchemy
tables remain as a local working mirror so the storefront and admin UI can
continue using the existing models while the catalog moves to Sheets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import gspread

from app import db
from app.models import (
    Book,
    Category,
    Inventory,
    Shelf,
    book_categories,
    book_shelves,
)

logger = logging.getLogger(__name__)

SHEET_HEADERS = [
    "id",
    "title",
    "subtitle",
    "author",
    "isbn",
    "publisher",
    "published_date",
    "description",
    "pages",
    "language",
    "cover_image",
    "preview_link",
    "price",
    "stock",
    "condition",
    "is_featured",
    "categories",
    "shelves",
    "created_at",
    "date_added",
]

VALID_CONDITIONS = {"New", "Like New", "Good", "Fair"}
SYNC_TTL_SECONDS = 10

_sync_lock = threading.RLock()
_last_sync_at = 0.0
_last_signature = None


def is_configured():
    """Return whether the Google Sheets catalog is configured.

    A partially configured setup is treated as an error rather than silently
    falling back to SQLite, because that could make edits appear to succeed
    while the sheet remains unchanged.
    """

    keys = (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        "GOOGLE_SHEETS_WORKSHEET",
    )
    present = [bool(os.environ.get(key, "").strip()) for key in keys]
    if any(present) and not all(present):
        missing = [key for key, value in zip(keys, present) if not value]
        raise RuntimeError(
            "Google Sheets catalog configuration is incomplete. "
            f"Missing: {', '.join(missing)}"
        )
    return all(present)


def initialize():
    """Load the sheet into the local mirror, or migrate the mirror to a blank sheet."""

    if not is_configured():
        logger.info("Google Sheets catalog is not configured; keeping SQLite catalog active.")
        return

    with _sync_lock:
        records = _read_sheet_records()
        if records:
            _replace_local_catalog(records)
            _remember_signature(records)
            logger.info("Loaded %s catalog books from Google Sheets.", len(records))
            return

        local_rows = _local_rows()
        if len(local_rows) > 1:
            _write_sheet_rows(local_rows)
            _remember_signature(local_rows[1:])
            logger.info(
                "Google Sheets Books worksheet was empty; migrated %s local books to it.",
                len(local_rows) - 1,
            )
        else:
            _remember_signature([])
            logger.info("Google Sheets Books worksheet is empty.")


def sync_from_sheet_if_needed(force=False):
    """Refresh the local mirror when the worksheet changed or the TTL expired."""

    if not is_configured():
        return

    global _last_sync_at
    now = time.monotonic()
    if not force and _last_sync_at and now - _last_sync_at < SYNC_TTL_SECONDS:
        return

    with _sync_lock:
        now = time.monotonic()
        if not force and _last_sync_at and now - _last_sync_at < SYNC_TTL_SECONDS:
            return
        records = _read_sheet_records()
        signature = _signature(records)
        if signature != _last_signature:
            _replace_local_catalog(records)
            logger.info("Refreshed local catalog mirror from Google Sheets.")
        _remember_signature(records)


def sync_to_sheet():
    """Write the current local catalog mirror to the Books worksheet."""

    if not is_configured():
        return

    with _sync_lock:
        rows = _local_rows()
        _write_sheet_rows(rows)
        _remember_signature(rows[1:])
        logger.info("Pushed %s catalog books to Google Sheets.", len(rows) - 1)


def _client_and_worksheet():
    credentials_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    spreadsheet_id = os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"]
    worksheet_name = os.environ["GOOGLE_SHEETS_WORKSHEET"]

    client = gspread.service_account(filename=credentials_path)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(worksheet_name)
    return worksheet


def _read_sheet_records():
    worksheet = _client_and_worksheet()
    values = worksheet.get_all_values()
    if not values:
        return []

    headers = [str(value).strip() for value in values[0]]
    if headers != SHEET_HEADERS:
        raise RuntimeError(
            "The Google Sheets worksheet headers do not match the expected Books schema. "
            f"Expected {len(SHEET_HEADERS)} columns in this order."
        )

    records = []
    for row_number, row in enumerate(values[1:], start=2):
        padded = list(row[: len(SHEET_HEADERS)])
        padded.extend([""] * (len(SHEET_HEADERS) - len(padded)))
        if not any(str(value).strip() for value in padded):
            continue
        record = dict(zip(SHEET_HEADERS, padded))
        record["_row_number"] = row_number
        records.append(record)
    return records


def _replace_local_catalog(records):
    """Replace the local catalog mirror with worksheet rows."""

    parsed_rows = [_parse_record(record, index) for index, record in enumerate(records, start=1)]
    ids = [row["id"] for row in parsed_rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("The Google Sheets catalog contains duplicate book IDs.")

    db.session.execute(book_categories.delete())
    db.session.execute(book_shelves.delete())
    db.session.query(Inventory).delete(synchronize_session=False)
    db.session.query(Book).delete(synchronize_session=False)
    db.session.query(Category).delete(synchronize_session=False)
    db.session.query(Shelf).delete(synchronize_session=False)

    categories_by_name = {}
    shelves_by_name = {}

    for row in parsed_rows:
        book = Book(
            id=row["id"],
            title=row["title"],
            subtitle=row["subtitle"],
            author=row["author"],
            isbn=row["isbn"] or None,
            publisher=row["publisher"],
            published_date=row["published_date"],
            description=row["description"],
            pages=row["pages"],
            language=row["language"],
            cover_image=row["cover_image"],
            preview_link=row["preview_link"],
            created_at=row["created_at"],
        )

        for name in row["categories"]:
            category = categories_by_name.get(name)
            if category is None:
                category = Category(name=name, slug=_slugify(name))
                categories_by_name[name] = category
            book.categories.append(category)

        for name in row["shelves"]:
            shelf = shelves_by_name.get(name)
            if shelf is None:
                shelf = Shelf(name=name, slug=_slugify(name), description="")
                shelves_by_name[name] = shelf
            book.shelves.append(shelf)

        book.inventory = Inventory(
            price=row["price"],
            stock=row["stock"],
            condition=row["condition"],
            is_featured=row["is_featured"],
            date_added=row["date_added"],
        )
        db.session.add(book)

    db.session.commit()


def _parse_record(record, fallback_id):
    book_id_text = _text(record.get("id"))
    try:
        book_id = int(book_id_text)
    except (TypeError, ValueError):
        book_id = fallback_id
    if book_id < 1:
        raise RuntimeError("Every Google Sheets book ID must be a positive integer.")

    title = _text(record.get("title"))
    author = _text(record.get("author"))
    if not title or not author:
        raise RuntimeError("Every Google Sheets book must have a title and author.")

    condition = _text(record.get("condition")) or "Good"
    if condition not in VALID_CONDITIONS:
        raise RuntimeError(
            f"Invalid condition {condition!r} for book {book_id}. "
            f"Use one of: {', '.join(sorted(VALID_CONDITIONS))}."
        )

    return {
        "id": book_id,
        "title": title,
        "subtitle": _text(record.get("subtitle")),
        "author": author,
        "isbn": _text(record.get("isbn")),
        "publisher": _text(record.get("publisher")),
        "published_date": _text(record.get("published_date")),
        "description": _text(record.get("description")),
        "pages": _int_or_none(record.get("pages")),
        "language": _text(record.get("language")) or "English",
        "cover_image": _text(record.get("cover_image")) or "images/covers/cover-01.jpg",
        "preview_link": _text(record.get("preview_link")),
        "price": _non_negative_float(record.get("price"), "price", book_id),
        "stock": _non_negative_int(record.get("stock"), "stock", book_id),
        "condition": condition,
        "is_featured": _bool(record.get("is_featured")),
        "categories": _split_values(record.get("categories")),
        "shelves": _split_values(record.get("shelves")),
        "created_at": _datetime_or_now(record.get("created_at")),
        "date_added": _datetime_or_now(record.get("date_added")),
    }


def _local_rows():
    rows = [SHEET_HEADERS]
    for book in Book.query.order_by(Book.id.asc()).all():
        rows.append(
            [
                book.id,
                book.title,
                book.subtitle or "",
                book.author,
                book.isbn or "",
                book.publisher or "",
                book.published_date or "",
                book.description or "",
                book.pages if book.pages is not None else "",
                book.language or "",
                book.cover_image or "",
                book.preview_link or "",
                book.price if book.price is not None else 0,
                book.stock,
                book.condition or "Good",
                "TRUE" if book.is_featured else "FALSE",
                "|".join(category.name for category in book.categories),
                "|".join(shelf.name for shelf in book.shelves),
                _format_datetime(book.created_at),
                _format_datetime(book.date_added),
            ]
        )
    return rows


def _write_sheet_rows(rows):
    worksheet = _client_and_worksheet()
    worksheet.clear()
    worksheet.update(values=rows, range_name="A1")


def _remember_signature(records):
    global _last_signature, _last_sync_at
    _last_signature = _signature(records)
    _last_sync_at = time.monotonic()


def _signature(records):
    clean_records = []
    for record in records:
        if isinstance(record, dict):
            clean_records.append(
                {key: value for key, value in record.items() if key != "_row_number"}
            )
        else:
            values = list(record[: len(SHEET_HEADERS)])
            values.extend([""] * (len(SHEET_HEADERS) - len(values)))
            clean_records.append(dict(zip(SHEET_HEADERS, values)))
    payload = json.dumps(clean_records, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value):
    return str(value or "").strip()


def _int_or_none(value):
    text = _text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid integer value: {value!r}") from None


def _non_negative_int(value, field, book_id):
    parsed = _int_or_none(value)
    if parsed is None:
        return 0
    if parsed < 0:
        raise RuntimeError(f"{field} cannot be negative for book {book_id}.")
    return parsed


def _non_negative_float(value, field, book_id):
    text = _text(value)
    if not text:
        return 0.0
    try:
        parsed = float(text)
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid {field} value for book {book_id}.") from None
    if parsed < 0:
        raise RuntimeError(f"{field} cannot be negative for book {book_id}.")
    return parsed


def _bool(value):
    return _text(value).casefold() in {"true", "1", "yes", "on"}


def _split_values(value):
    return [part.strip() for part in _text(value).split("|") if part.strip()]


def _datetime_or_now(value):
    text = _text(value)
    if not text:
        return datetime.utcnow()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError(f"Invalid ISO date/time value: {value!r}") from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _format_datetime(value):
    return value.isoformat() if value else ""


def _slugify(value):
    return (
        value.strip()
        .lower()
        .replace("&", "and")
        .replace("'", "")
        .replace(" ", "-")
    )