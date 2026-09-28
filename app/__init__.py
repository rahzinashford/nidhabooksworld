"""Application factory for Nidha Books World."""

import os

from flask import Flask, request, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite ignores FK constraints (like Inventory's ondelete=CASCADE)
    unless this pragma is set per-connection. Without it, deleting a Book
    outside the ORM's cascade (e.g. a manual/partial delete) can leave an
    orphaned Inventory row behind, which later collides on book_id once
    SQLite reuses the freed row id for a new Book.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _run_migrations(db_instance):
    """Apply lightweight ALTER TABLE migrations for columns added after the
    initial schema was created.  SQLite supports adding nullable columns
    without rebuilding the table, so we use that rather than a full
    migration framework.  Each statement is wrapped individually so a
    column that already exists (``OperationalError: duplicate column name``)
    is silently skipped.
    """
    new_columns = [
        "ALTER TABLE books ADD COLUMN subtitle VARCHAR(300) DEFAULT ''",
        "ALTER TABLE books ADD COLUMN published_date VARCHAR(40) DEFAULT ''",
        "ALTER TABLE books ADD COLUMN preview_link VARCHAR(300) DEFAULT ''",
    ]
    with db_instance.engine.connect() as conn:
        for stmt in new_columns:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:  # noqa: BLE001 — column already exists, skip
                conn.rollback()


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("config.Config")

    # The dev preview proxies through a Vite server with `changeOrigin: true`,
    # which rewrites the Host header Flask sees to the backend's own
    # "localhost:<port>". Werkzeug's automatic trailing-slash redirect
    # (e.g. /admin -> /admin/) builds its Location header from that Host,
    # so it would send browsers straight to localhost instead of the real
    # preview domain. Disabling strict slashes avoids that redirect entirely.
    app.url_map.strict_slashes = False

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    from app.routes import main_bp

    app.register_blueprint(main_bp)

    from app.admin_routes import admin_bp

    app.register_blueprint(admin_bp)

    from app import models  # noqa: F401  (ensures models are registered)

    with app.app_context():
        db.create_all()
        _run_migrations(db)
        from app.seed import seed_if_empty

        seed_if_empty()
        from app.services import sheet_sync

        sheet_sync.initialize()

    @app.before_request
    def refresh_catalog_from_sheet():
        if request.endpoint != "static":
            from app.services import sheet_sync

            sheet_sync.sync_from_sheet_if_needed()

    @app.after_request
    def persist_admin_catalog_changes(response):
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.path.startswith("/admin/")
            and request.endpoint not in {"admin.login", "admin.logout"}
        ):
            from app.services import sheet_sync

            sheet_sync.sync_to_sheet()
        return response

    @app.context_processor
    def inject_store_settings():
        from app.models import Setting

        # Settings live in the database (seeded from config.py defaults) so
        # store details can be edited without a code change; fall back to
        # the static config values if a key is somehow missing.
        rows = {s.key: s.value for s in Setting.query.all()}
        cart = session.get("cart", {})
        cart_count = 0
        if isinstance(cart, dict):
            for quantity in cart.values():
                try:
                    cart_count += max(0, int(quantity))
                except (TypeError, ValueError):
                    continue
        return {
            "store_name": rows.get("store_name", app.config["STORE_NAME"]),
            "store_tagline": rows.get("store_tagline", app.config["STORE_TAGLINE"]),
            "delivery_info": rows.get("delivery_info", app.config["DELIVERY_INFO"]),
            "whatsapp_number": rows.get("whatsapp_number", app.config["WHATSAPP_NUMBER"]),
            "cart_count": cart_count,
        }

    @app.template_filter("inr")
    def format_inr(value):
        """Format a number as Indian Rupees, e.g. 250 -> '\u20b9250'."""
        symbol = app.config.get("CURRENCY_SYMBOL", "\u20b9")
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return value
        if amount == int(amount):
            return f"{symbol}{int(amount):,}"
        return f"{symbol}{amount:,.2f}"

    @app.template_global("cover_url")
    def cover_url(cover_image):
        """Resolve a book's cover image to a usable <img src>.

        Imported books store a full https:// URL from Google Books/Open
        Library directly; locally seeded books store a filename under
        static/images/covers/. Templates call this instead of hardcoding
        url_for('static', ...) so both kinds of cover render correctly.
        """
        from flask import url_for

        if not cover_image:
            return url_for("static", filename="images/covers/cover-01.jpg")
        if cover_image.startswith("http://") or cover_image.startswith("https://"):
            return cover_image
        return url_for("static", filename=cover_image)

    @app.template_filter("stars")
    def render_stars(rating):
        """Render a 0-5 rating as filled/empty star glyphs."""
        try:
            value = float(rating)
        except (TypeError, ValueError):
            value = 0
        full = max(0, min(5, round(value)))
        return "\u2605" * full + "\u2606" * (5 - full)

    return app
