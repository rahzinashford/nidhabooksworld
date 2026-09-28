"""HTTP routes for Nidha Books World."""

from urllib.parse import quote

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from app.models import Book, Category, Inventory, Setting

main_bp = Blueprint("main", __name__)
CART_SESSION_KEY = "cart"
CHECKOUT_SESSION_KEY = "checkout_contact"


def apply_search(query, term):
    """Search across title, author, ISBN, publisher, and category name."""
    like = f"%{term}%"
    conditions = [
        Book.title.ilike(like),
        Book.author.ilike(like),
        Book.isbn.ilike(like),
        Book.publisher.ilike(like),
        Book.categories.any(Category.name.ilike(like)),
    ]
    return query.filter(or_(*conditions))


def all_category_names():
    return [c.name for c in Category.query.order_by(Category.name.asc()).all()]


def category_shelf_counts(limit=8):
    """Categories with at least one in-stock book, ordered by how full the
    shelf is (most copies first) -- for the homepage's "Browse by Category"
    card catalog, where a fuller shelf is a more inviting one to open.
    """
    categories = Category.query.all()
    counts = []
    for category in categories:
        count = category.books.join(Inventory).filter(Inventory.stock > 0).count()
        if count:
            counts.append({"name": category.name, "count": count})
    counts.sort(key=lambda c: (-c["count"], c["name"]))
    return counts[:limit]


def cart_item_count():
    """Return the number of copies currently held in the visitor's cart."""
    cart = session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        return 0
    total = 0
    for quantity in cart.values():
        try:
            total += max(0, int(quantity))
        except (TypeError, ValueError):
            continue
    return total


def _get_cart():
    """Read a normalized ``{book_id: quantity}`` cart from the session."""
    raw = session.get(CART_SESSION_KEY, {})
    if not isinstance(raw, dict):
        return {}

    cart = {}
    for book_id, quantity in raw.items():
        try:
            book_id = int(book_id)
            quantity = int(quantity)
        except (TypeError, ValueError):
            continue
        if book_id > 0 and quantity > 0:
            cart[str(book_id)] = quantity
    return cart


def _save_cart(cart):
    session[CART_SESSION_KEY] = {
        str(book_id): int(quantity)
        for book_id, quantity in cart.items()
        if int(quantity) > 0
    }
    session.modified = True


def _cart_lines():
    """Return stock-validated cart lines, subtotal, and item count."""
    cart = _get_cart()
    if not cart:
        return [], 0.0, 0

    ids = [int(book_id) for book_id in cart]
    books = Book.query.filter(Book.id.in_(ids)).all()
    books_by_id = {str(book.id): book for book in books}
    clean_cart = {}
    lines = []

    for book_id, requested_quantity in cart.items():
        book = books_by_id.get(book_id)
        if book is None or book.inventory is None or book.stock <= 0:
            continue

        quantity = min(requested_quantity, book.stock)
        clean_cart[book_id] = quantity
        lines.append(
            {
                "book": book,
                "quantity": quantity,
                "line_total": float(book.price or 0) * quantity,
            }
        )

    if clean_cart != cart:
        _save_cart(clean_cart)

    subtotal = sum(line["line_total"] for line in lines)
    item_count = sum(line["quantity"] for line in lines)
    return lines, subtotal, item_count


def _store_whatsapp_number():
    setting = Setting.query.filter_by(key="whatsapp_number").first()
    return (setting.value if setting and setting.value else current_app.config["WHATSAPP_NUMBER"]).strip()


def _format_currency(amount):
    symbol = current_app.config.get("CURRENCY_SYMBOL", "\u20b9")
    amount = float(amount or 0)
    if amount == int(amount):
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:,.2f}"


def _build_order_message(contact, lines, subtotal):
    book_lines = []
    for index, line in enumerate(lines, start=1):
        book = line["book"]
        book_lines.extend(
            [
                f"{index}. {book.title}",
                f"   Author: {book.author}",
                f"   Quantity: {line['quantity']}",
                f"   Unit price: {_format_currency(book.price)}",
                f"   Line total: {_format_currency(line['line_total'])}",
            ]
        )

    return "\n".join(
        [
            "Hello Nidha Books World,",
            "",
            "I would like to place this order:",
            "",
            *book_lines,
            "",
            f"Books subtotal: {_format_currency(subtotal)}",
            "Delivery charges: To be confirmed on WhatsApp",
            f"Total before delivery: {_format_currency(subtotal)}",
            "",
            "Delivery details:",
            f"Name: {contact['name']}",
            f"Phone: {contact['phone']}",
            "Address:",
            contact["address"],
            "",
            "Please confirm availability, delivery charges, and the final total.",
        ]
    )


@main_bp.route("/")
def home():
    featured = (
        Book.query.join(Inventory)
        .filter(Inventory.is_featured.is_(True), Inventory.stock > 0)
        .limit(6)
        .all()
    )
    recent = (
        Book.query.join(Inventory)
        .filter(Inventory.stock > 0)
        .order_by(Inventory.date_added.desc())
        .limit(8)
        .all()
    )
    genres = all_category_names()
    categories = category_shelf_counts()
    return render_template(
        "index.html",
        featured=featured,
        recent=recent,
        genres=genres,
        categories=categories,
    )


@main_bp.route("/browse")
def browse():
    query = Book.query.join(Inventory)

    search = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    condition = request.args.get("condition", "").strip()

    if search:
        query = apply_search(query, search)
    if genre:
        query = query.filter(Book.categories.any(Category.name == genre))
    if condition:
        query = query.filter(Inventory.condition == condition)

    books = query.order_by(Book.title.asc()).all()
    genres = all_category_names()
    conditions = ["New", "Like New", "Good", "Fair"]

    return render_template(
        "browse.html",
        books=books,
        genres=genres,
        conditions=conditions,
        active_search=search,
        active_genre=genre,
        active_condition=condition,
    )


@main_bp.route("/books/<int:book_id>")
def book_detail(book_id):
    book = Book.query.get(book_id)
    if book is None:
        abort(404)
    category_ids = [c.id for c in book.categories]
    related = (
        Book.query.join(Inventory)
        .filter(
            Book.categories.any(Category.id.in_(category_ids)) if category_ids else False,
            Book.id != book.id,
            Inventory.stock > 0,
        )
        .limit(4)
        .all()
    )
    return render_template("book_detail.html", book=book, related=related)


@main_bp.route("/cart")
def cart():
    lines, subtotal, item_count = _cart_lines()
    return render_template(
        "cart.html",
        lines=lines,
        subtotal=subtotal,
        item_count=item_count,
    )


@main_bp.route("/cart/add/<int:book_id>", methods=["POST"])
def cart_add(book_id):
    book = Book.query.get_or_404(book_id)
    if book.inventory is None or not book.in_stock:
        flash(f'"{book.title}" is currently unavailable.', "error")
        return redirect(url_for("main.book_detail", book_id=book.id))

    try:
        requested_quantity = max(1, int(request.form.get("quantity", 1)))
    except (TypeError, ValueError):
        requested_quantity = 1

    cart = _get_cart()
    current_quantity = cart.get(str(book.id), 0)
    quantity = min(book.stock, current_quantity + requested_quantity)
    cart[str(book.id)] = quantity
    _save_cart(cart)

    if quantity < current_quantity + requested_quantity:
        flash(f'"{book.title}" is limited to the {book.stock} available in stock.', "error")
    else:
        flash(f'"{book.title}" was added to your cart.', "success")
    return redirect(url_for("main.book_detail", book_id=book.id))


@main_bp.route("/cart/update", methods=["POST"])
def cart_update():
    cart = _get_cart()
    remove_id = request.form.get("remove_id", "").strip()
    if remove_id:
        cart.pop(remove_id, None)
        _save_cart(cart)
        flash("Book removed from your cart.", "success")
        return redirect(url_for("main.cart"))

    updated_cart = {}
    for book_id in cart:
        try:
            quantity = int(request.form.get(f"quantity_{book_id}", 0))
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            continue
        book = Book.query.get(int(book_id))
        if book and book.inventory and book.stock > 0:
            updated_cart[book_id] = min(quantity, book.stock)

    _save_cart(updated_cart)
    flash("Your cart was updated.", "success")
    return redirect(url_for("main.cart"))


@main_bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines, subtotal, item_count = _cart_lines()
    if not lines:
        flash("Add at least one available book before checking out.", "error")
        return redirect(url_for("main.cart"))

    contact = session.get(CHECKOUT_SESSION_KEY, {})
    errors = []
    if request.method == "POST":
        contact = {
            "name": request.form.get("name", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "address": request.form.get("address", "").strip(),
        }
        if not contact["name"]:
            errors.append("Please enter your name.")
        elif len(contact["name"]) > 120:
            errors.append("Please keep your name under 120 characters.")
        if not contact["phone"]:
            errors.append("Please enter your phone number.")
        elif len(contact["phone"]) > 40:
            errors.append("Please keep your phone number under 40 characters.")
        if not contact["address"]:
            errors.append("Please enter the delivery address.")
        elif len(contact["address"]) > 500:
            errors.append("Please keep the delivery address under 500 characters.")

        if not errors:
            session[CHECKOUT_SESSION_KEY] = contact
            return redirect(url_for("main.order_confirmation"))

    return render_template(
        "checkout.html",
        lines=lines,
        subtotal=subtotal,
        item_count=item_count,
        contact=contact,
        errors=errors,
    )


@main_bp.route("/order/confirmation")
def order_confirmation():
    contact = session.get(CHECKOUT_SESSION_KEY)
    lines, subtotal, item_count = _cart_lines()
    if not contact:
        return redirect(url_for("main.checkout"))
    if not lines:
        flash("Your cart is empty. Add a book before confirming the order.", "error")
        return redirect(url_for("main.cart"))

    return render_template(
        "order_confirmation.html",
        contact=contact,
        lines=lines,
        subtotal=subtotal,
        item_count=item_count,
    )


@main_bp.route("/order/place", methods=["POST"])
def order_place():
    contact = session.get(CHECKOUT_SESSION_KEY)
    lines, subtotal, _item_count = _cart_lines()
    if not contact:
        return redirect(url_for("main.checkout"))
    if not lines:
        flash("Your cart is empty. Add a book before placing the order.", "error")
        return redirect(url_for("main.cart"))

    message = _build_order_message(contact, lines, subtotal)
    whatsapp_number = "".join(character for character in _store_whatsapp_number() if character.isdigit())
    session.pop(CART_SESSION_KEY, None)
    session.pop(CHECKOUT_SESSION_KEY, None)
    return redirect(f"https://wa.me/{whatsapp_number}?text={quote(message)}")


@main_bp.route("/about")
def about():
    return render_template("about.html")


@main_bp.route("/api/books")
def api_books():
    """Lightweight JSON endpoint used by the browse page's live search."""
    search = request.args.get("q", "").strip()
    query = Book.query.join(Inventory).filter(Inventory.stock > 0)
    if search:
        query = apply_search(query, search)
    books = query.order_by(Book.title.asc()).all()
    return jsonify([b.to_dict() for b in books])


@main_bp.route("/api/suggest")
def api_suggest():
    """Instant search suggestions as the shopper types.

    Matches title, author, ISBN, category, and publisher, and returns a
    small, card-friendly payload for the suggestions dropdown.
    """
    term = request.args.get("q", "").strip()
    if len(term) < 2:
        return jsonify([])

    query = apply_search(Book.query.join(Inventory).filter(Inventory.stock > 0), term)
    books = query.order_by(Book.title.asc()).limit(6).all()
    return jsonify(
        [
            {
                "id": b.id,
                "title": b.title,
                "author": b.author,
                "genre": b.genre,
                "cover_image": b.cover_image,
                "price": b.price,
            }
            for b in books
        ]
    )


@main_bp.app_errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404
