"""Admin dashboard routes for Nidha Books World.

A lightweight, session-based admin area protected by a single shared
password (``ADMIN_PASSWORD`` env var / Replit secret) -- there are no user
accounts, just one login gate in front of the store-management screens.
"""

import hmac
import os
import re
from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from app import book_import, db
from app.models import Book, Category, Inventory, Setting, Shelf
from app.services import book_import_service, image_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

CONDITIONS = ["New", "Like New", "Good", "Fair"]


def _slugify(name):
    return name.strip().lower().replace("&", "and").replace("'", "").replace(" ", "-")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_authenticated"):
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        submitted = request.form.get("password", "").strip()
        expected = os.environ.get("ADMIN_PASSWORD", "").strip()
        if expected and hmac.compare_digest(submitted, expected):
            session["admin_authenticated"] = True
            session.permanent = True
            next_url = request.args.get("next") or url_for("admin.dashboard")
            return redirect(next_url)
        flash("Incorrect password.", "error")

    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("admin_authenticated", None)
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@login_required
def dashboard():
    total_books = Book.query.count()
    total_stock = db.session.query(db.func.coalesce(db.func.sum(Inventory.stock), 0)).scalar()
    inventory_value = db.session.query(
        db.func.coalesce(db.func.sum(Inventory.price * Inventory.stock), 0)
    ).scalar()
    featured_count = Inventory.query.filter_by(is_featured=True).count()
    low_stock = (
        Book.query.join(Inventory)
        .filter(Inventory.stock > 0, Inventory.stock <= 2)
        .order_by(Inventory.stock.asc())
        .limit(6)
        .all()
    )
    out_of_stock_count = Inventory.query.filter(Inventory.stock == 0).count()
    recent_books = Book.query.join(Inventory).order_by(Inventory.date_added.desc()).limit(5).all()

    return render_template(
        "admin/dashboard.html",
        total_books=total_books,
        total_stock=total_stock,
        inventory_value=inventory_value,
        featured_count=featured_count,
        low_stock=low_stock,
        out_of_stock_count=out_of_stock_count,
        recent_books=recent_books,
    )


# --- Books --------------------------------------------------------------


@admin_bp.route("/books")
@login_required
def books():
    search = request.args.get("q", "").strip()
    query = Book.query.join(Inventory)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(Book.title.ilike(like), Book.author.ilike(like), Book.isbn.ilike(like))
        )
    book_list = query.order_by(Book.title.asc()).all()
    return render_template("admin/books.html", books=book_list, active_search=search)


def _apply_book_form(book, inventory):
    book.title = request.form.get("title", "").strip()
    book.author = request.form.get("author", "").strip()
    book.isbn = request.form.get("isbn", "").strip() or None
    book.publisher = request.form.get("publisher", "").strip()
    book.description = request.form.get("description", "").strip()
    pages = request.form.get("pages", "").strip()
    book.pages = int(pages) if pages.isdigit() else None
    book.language = request.form.get("language", "").strip() or "English"
    book.cover_image = request.form.get("cover_image", "").strip() or "images/covers/cover-01.jpg"

    category_ids = request.form.getlist("category_ids")
    book.categories = Category.query.filter(Category.id.in_(category_ids)).all() if category_ids else []

    new_category_names = [
        n.strip() for n in request.form.get("new_categories", "").split(",") if n.strip()
    ]
    for name in new_category_names:
        existing = Category.query.filter(db.func.lower(Category.name) == name.lower()).first()
        if existing is None:
            existing = Category(name=name, slug=_slugify(name))
            db.session.add(existing)
        if existing not in book.categories:
            book.categories.append(existing)

    shelf_ids = request.form.getlist("shelf_ids")
    book.shelves = Shelf.query.filter(Shelf.id.in_(shelf_ids)).all() if shelf_ids else []

    inventory.price = float(request.form.get("price") or 0)
    inventory.stock = int(request.form.get("stock") or 0)
    inventory.condition = request.form.get("condition", "Good")
    inventory.is_featured = request.form.get("is_featured") == "on"


@admin_bp.route("/books/new", methods=["GET", "POST"])
@login_required
def book_new():
    if request.method == "POST":
        book = Book(cover_image="images/covers/cover-01.jpg")
        inventory = Inventory(price=0, stock=0)
        book.inventory = inventory
        _apply_book_form(book, inventory)
        db.session.add(book)
        db.session.commit()
        flash(f'"{book.title}" was added.', "success")
        return redirect(url_for("admin.books"))

    return render_template(
        "admin/book_form.html",
        book=None,
        categories=Category.query.order_by(Category.name.asc()).all(),
        shelves=Shelf.query.order_by(Shelf.name.asc()).all(),
        conditions=CONDITIONS,
    )


@admin_bp.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@login_required
def book_edit(book_id):
    book = Book.query.get_or_404(book_id)
    if book.inventory is None:
        book.inventory = Inventory(price=0, stock=0)

    if request.method == "POST":
        _apply_book_form(book, book.inventory)
        db.session.commit()
        flash(f'"{book.title}" was updated.', "success")
        return redirect(url_for("admin.books"))

    return render_template(
        "admin/book_form.html",
        book=book,
        categories=Category.query.order_by(Category.name.asc()).all(),
        shelves=Shelf.query.order_by(Shelf.name.asc()).all(),
        conditions=CONDITIONS,
    )


def _candidate_from_form():
    """Rebuild a metadata dict from the hidden fields carried through the import form."""
    categories = [c.strip() for c in request.form.get("categories", "").split(",") if c.strip()]
    pages = request.form.get("pages", "").strip()
    return {
        "title": request.form.get("title", "").strip(),
        "author": request.form.get("author", "").strip(),
        "isbn": request.form.get("isbn", "").strip(),
        "description": request.form.get("description", "").strip(),
        "publisher": request.form.get("publisher", "").strip(),
        "pages": int(pages) if pages.isdigit() else None,
        "categories": categories,
        "cover_image": request.form.get("cover_image", "").strip(),
        "language": request.form.get("language", "").strip(),
    }


@admin_bp.route("/books/import", methods=["GET"])
@login_required
def book_import_search():
    """Render the JS-driven book import page."""
    return render_template("admin/import.html", conditions=CONDITIONS)


# ---------------------------------------------------------------------------
# JSON API — used by the JS import flow
# ---------------------------------------------------------------------------


@admin_bp.route("/books/search")
@login_required
def book_search_api():
    """GET /admin/books/search?q=<query>&source=<provider>

    Returns JSON search results from the selected provider or all providers.
    """
    q = request.args.get("q", "").strip()
    source = request.args.get("source", "all").strip() or "all"
    if not q:
        return jsonify({"error": "Query required"}), 400
    if source not in book_import_service.SOURCE_NAMES:
        return jsonify({"error": "Unknown metadata source"}), 400

    results, returned_source, errors = book_import_service.search(q, source)
    return jsonify({
        "results": results,
        "source": returned_source or source,
        "query": q,
        "errors": [{"source": s, "message": m} for s, m in errors],
    })


@admin_bp.route("/books/metadata")
@login_required
def book_metadata_api():
    """Return metadata for a selected ISBN from one provider or all providers."""
    isbn = request.args.get("isbn", "").strip()
    source = request.args.get("source", "all").strip() or "all"
    if not book_import_service.looks_like_isbn(isbn):
        return jsonify({"error": "A valid ISBN-10 or ISBN-13 is required"}), 400
    if source not in book_import_service.SOURCE_NAMES:
        return jsonify({"error": "Unknown metadata source"}), 400

    metadata, sources, errors = book_import_service.lookup_isbn(isbn, source)
    if metadata is None:
        return jsonify({
            "error": "No complete metadata was found for this ISBN",
            "sources": sources,
            "errors": [{"source": source, "message": message} for source, message in errors],
        }), 404

    return jsonify({
        "metadata": metadata,
        "sources": sources,
        "errors": [{"source": source, "message": message} for source, message in errors],
    })


@admin_bp.route("/books/import/json", methods=["POST"])
@login_required
def book_import_api():
    """POST /admin/books/import/json

    Import a book into the database. Accepts JSON payload with metadata
    + inventory fields. Returns JSON indicating success, duplicate, or error.

    Payload keys
    ------------
    title, subtitle, author, isbn, publisher, published_date, description,
    pages, language, categories (list), cover_image, preview_link,
    price, stock, condition, is_featured (bool),
    shelf_ids (list[int]), new_category_names (list[str]),
    force_update_stock (bool) — if True and book_id present, update stock,
    book_id (int) — required when force_update_stock is True.
    """
    data = request.get_json(force=True) or {}

    # --- Handle "update stock of existing book" branch ---
    if data.get("force_update_stock") and data.get("book_id"):
        return _update_existing_stock(data)

    isbn = (data.get("isbn") or "").strip()
    title = (data.get("title") or "").strip()
    author = (data.get("author") or "").strip()

    if not title:
        return jsonify({"error": "Book title is required"}), 400

    # --- Duplicate detection ---
    duplicate = book_import_service.find_duplicate(isbn, title, author)
    if duplicate:
        return jsonify({
            "duplicate": True,
            "book_id": duplicate.id,
            "title": duplicate.title,
            "author": duplicate.author,
            "current_stock": duplicate.stock,
        })

    # --- Download cover locally ---
    cover = (data.get("cover_image") or "").strip()
    if cover.startswith("http"):
        identifier = isbn or re.sub(r"[^a-zA-Z0-9]", "-", title)[:40]
        local = image_service.download_cover(cover, identifier)
        if local:
            cover = local

    if not cover:
        cover = "images/covers/cover-01.jpg"

    # --- Create Book ---
    pages_raw = data.get("pages")
    try:
        pages = int(pages_raw) if pages_raw else None
    except (TypeError, ValueError):
        pages = None

    book = Book(
        title=title,
        subtitle=(data.get("subtitle") or "").strip(),
        author=author or "Unknown",
        isbn=isbn or None,
        publisher=(data.get("publisher") or "").strip(),
        published_date=(data.get("published_date") or "").strip(),
        description=(data.get("description") or "").strip(),
        pages=pages,
        language=(data.get("language") or "English").strip(),
        cover_image=cover,
        preview_link=(data.get("preview_link") or "").strip(),
    )
    db.session.add(book)

    # --- Categories ---
    raw_cats = data.get("categories") or []
    if isinstance(raw_cats, str):
        raw_cats = [c.strip() for c in raw_cats.split(",") if c.strip()]
    for name in raw_cats:
        cat = Category.query.filter(db.func.lower(Category.name) == name.lower()).first()
        if cat is None:
            cat = Category(name=name, slug=_slugify(name))
            db.session.add(cat)
        book.categories.append(cat)

    # Extra category names passed separately
    for name in (data.get("new_category_names") or []):
        name = name.strip()
        if not name:
            continue
        cat = Category.query.filter(db.func.lower(Category.name) == name.lower()).first()
        if cat is None:
            cat = Category(name=name, slug=_slugify(name))
            db.session.add(cat)
        if cat not in book.categories:
            book.categories.append(cat)

    # --- Shelves ---
    shelf_ids = data.get("shelf_ids") or []
    if shelf_ids:
        book.shelves = Shelf.query.filter(Shelf.id.in_(shelf_ids)).all()

    # --- Inventory ---
    try:
        price = max(0.0, float(data.get("price") or 0))
        stock = max(0, int(data.get("stock") or 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Price and stock must be numbers"}), 400

    book.inventory = Inventory(
        price=price,
        stock=stock,
        condition=data.get("condition", "Good"),
        is_featured=bool(data.get("is_featured", False)),
    )

    db.session.commit()
    return jsonify({"success": True, "book_id": book.id, "title": book.title})


def _update_existing_stock(data):
    """Update inventory on an existing book (duplicate detected path)."""
    book = Book.query.get(data.get("book_id"))
    if book is None:
        return jsonify({"error": "Book not found"}), 404

    if book.inventory is None:
        book.inventory = Inventory(price=0, stock=0)
        db.session.add(book.inventory)

    try:
        additional = max(0, int(data.get("additional_stock") or 0))
        price = float(data.get("price") or book.inventory.price)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid stock or price value"}), 400

    book.inventory.stock += additional
    book.inventory.price = max(0.0, price)
    if data.get("condition"):
        book.inventory.condition = data["condition"]

    db.session.commit()
    return jsonify({
        "success": True,
        "updated": True,
        "book_id": book.id,
        "title": book.title,
        "new_stock": book.inventory.stock,
    })


@admin_bp.route("/books/import/select", methods=["POST"])
@login_required
def book_import_select():
    """Step 2: admin picked a candidate from a free-text search -- fill in the rest via ISBN."""
    candidate = _candidate_from_form()
    isbn = candidate.get("isbn", "")

    result = candidate
    sources = [request.form.get("source", "")] if request.form.get("source") else []
    if isbn and book_import.looks_like_isbn(isbn):
        merged, merge_sources, _errors = book_import_service.lookup_isbn(isbn)
        if merged is not None:
            result = book_import.merge_fields(merged, candidate)
            sources = merge_sources or sources

    return render_template(
        "admin/import.html", stage="preview", result=result, sources=sources, conditions=CONDITIONS
    )


@admin_bp.route("/books/import/confirm", methods=["POST"])
@login_required
def book_import_confirm():
    """Step 3: admin only supplies price/stock/condition -- everything else came from the API."""
    candidate = _candidate_from_form()
    if not candidate["title"]:
        flash("Missing book title -- please search again.", "error")
        return redirect(url_for("admin.book_import_search"))

    book = Book(
        title=candidate["title"],
        author=candidate["author"] or "Unknown",
        isbn=candidate["isbn"] or None,
        publisher=candidate["publisher"],
        description=candidate["description"],
        pages=candidate["pages"],
        language=candidate["language"] or "English",
        cover_image=candidate["cover_image"] or "images/covers/cover-01.jpg",
    )

    db.session.add(book)

    for name in candidate["categories"]:
        existing = Category.query.filter(db.func.lower(Category.name) == name.lower()).first()
        if existing is None:
            existing = Category(name=name, slug=_slugify(name))
            db.session.add(existing)
        book.categories.append(existing)

    try:
        price = float(request.form.get("price") or 0)
        stock = int(request.form.get("stock") or 0)
    except ValueError:
        flash("Price and stock must be numbers.", "error")
        return render_template(
            "admin/import.html", stage="preview", result=candidate, sources=[], conditions=CONDITIONS
        )

    book.inventory = Inventory(
        price=max(0.0, price),
        stock=max(0, stock),
        condition=request.form.get("condition", "Good"),
    )

    db.session.commit()
    flash(f'"{book.title}" was imported.', "success")
    return redirect(url_for("admin.books"))


@admin_bp.route("/books/<int:book_id>/delete", methods=["POST"])
@login_required
def book_delete(book_id):
    book = Book.query.get_or_404(book_id)
    title = book.title
    db.session.delete(book)
    db.session.commit()
    flash(f'"{title}" was deleted.', "success")
    return redirect(url_for("admin.books"))


@admin_bp.route("/books/<int:book_id>/feature", methods=["POST"])
@login_required
def book_toggle_feature(book_id):
    book = Book.query.get_or_404(book_id)
    if book.inventory:
        book.inventory.is_featured = not book.inventory.is_featured
        db.session.commit()
        state = "featured" if book.inventory.is_featured else "unfeatured"
        flash(f'"{book.title}" is now {state}.', "success")
    return redirect(request.referrer or url_for("admin.books"))


# --- Inventory ------------------------------------------------------------


@admin_bp.route("/inventory")
@login_required
def inventory():
    filter_stock = request.args.get("stock", "").strip()
    query = Book.query.join(Inventory)
    if filter_stock == "low":
        query = query.filter(Inventory.stock > 0, Inventory.stock <= 2)
    elif filter_stock == "out":
        query = query.filter(Inventory.stock == 0)
    book_list = query.order_by(Book.title.asc()).all()
    return render_template(
        "admin/inventory.html", books=book_list, conditions=CONDITIONS, active_filter=filter_stock
    )


@admin_bp.route("/inventory/<int:book_id>/update", methods=["POST"])
@login_required
def inventory_update(book_id):
    book = Book.query.get_or_404(book_id)
    inv = book.inventory
    if inv is None:
        flash("This book has no inventory record.", "error")
        return redirect(url_for("admin.inventory"))

    price = request.form.get("price")
    stock = request.form.get("stock")
    condition = request.form.get("condition")

    if price is not None:
        try:
            inv.price = max(0.0, float(price))
        except ValueError:
            flash("Price must be a number.", "error")
            return redirect(url_for("admin.inventory"))
    if stock is not None:
        try:
            inv.stock = max(0, int(stock))
        except ValueError:
            flash("Stock must be a whole number.", "error")
            return redirect(url_for("admin.inventory"))
    if condition:
        inv.condition = condition
    inv.is_featured = request.form.get("is_featured") == "on"

    db.session.commit()
    flash(f'"{book.title}" inventory updated.', "success")
    return redirect(request.referrer or url_for("admin.inventory"))


# --- Settings ---------------------------------------------------------------

SETTINGS_FIELDS = [
    ("store_name", "Store name"),
    ("store_tagline", "Tagline"),
    ("delivery_info", "Delivery details"),
    ("whatsapp_number", "WhatsApp number"),
    ("currency_symbol", "Currency symbol"),
]


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        for key, _label in SETTINGS_FIELDS:
            value = request.form.get(key, "").strip()
            setting = Setting.query.get(key)
            if setting is None:
                setting = Setting(key=key, value=value)
                db.session.add(setting)
            else:
                setting.value = value
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    rows = {s.key: s.value for s in Setting.query.all()}
    return render_template("admin/settings.html", fields=SETTINGS_FIELDS, values=rows)
