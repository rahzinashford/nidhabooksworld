"""Database models for Nidha Books World.

Schema overview
----------------
- ``Category``  -- a genre/subject a book can be shelved under (many-to-many).
- ``Shelf``     -- a curated grouping of books, e.g. "Staff Picks" (many-to-many).
- ``Book``      -- catalog metadata for a title: ISBN, author, publisher,
                    description, pages, language, cover image. This is
                    information about the *work*, independent of whether the
                    catalogue currently has a copy for sale.
- ``Inventory`` -- the sellable-copy data for a book: price, stock, condition,
                    featured flag, and the date that copy was added. Kept
                    separate from ``Book`` so metadata and stock/pricing can
                    evolve independently (e.g. re-pricing or restocking a
                    title never touches its catalog record).
- ``Setting``   -- simple key/value store for site configuration (store name,
                    contact number, delivery details, etc.) so it can be edited without
                    a code change.

Book <-> Category and Book <-> Shelf are many-to-many: a book can span
several categories (e.g. "Essays" and "Nature Writing") and appear on
several shelves (e.g. "Featured" and "Staff Picks"). Book <-> Inventory is
one-to-one today (one catalog record, one sellable copy), but the foreign
key lives on ``Inventory`` so it is easy to later support multiple physical
copies of the same title by relaxing the uniqueness constraint.
"""

from datetime import datetime

from app import db

# --- Association tables (many-to-many) --------------------------------

book_categories = db.Table(
    "book_categories",
    db.Column(
        "book_id", db.Integer, db.ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    ),
    db.Column(
        "category_id",
        db.Integer,
        db.ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

book_shelves = db.Table(
    "book_shelves",
    db.Column(
        "book_id", db.Integer, db.ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    ),
    db.Column(
        "shelf_id", db.Integer, db.ForeignKey("shelves.id", ondelete="CASCADE"), primary_key=True
    ),
)


class Category(db.Model):
    """A genre/subject used to classify books (e.g. "Poetry", "Mystery")."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)

    books = db.relationship(
        "Book", secondary=book_categories, back_populates="categories", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Category {self.name}>"


class Shelf(db.Model):
    """A curated grouping of books, independent of genre (e.g. "Just Arrived")."""

    __tablename__ = "shelves"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=False, default="")

    books = db.relationship(
        "Book", secondary=book_shelves, back_populates="shelves", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Shelf {self.name}>"


class Book(db.Model):
    """Catalog metadata for a title -- independent of price/stock."""

    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    isbn = db.Column(db.String(20), nullable=True, unique=True)
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(300), nullable=True, default="")
    author = db.Column(db.String(150), nullable=False)
    publisher = db.Column(db.String(150), nullable=False, default="")
    published_date = db.Column(db.String(40), nullable=True, default="")
    description = db.Column(db.Text, nullable=False, default="")
    pages = db.Column(db.Integer, nullable=True)
    language = db.Column(db.String(60), nullable=False, default="English")
    cover_image = db.Column(db.String(300), nullable=False)
    preview_link = db.Column(db.String(300), nullable=True, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    categories = db.relationship(
        "Category", secondary=book_categories, back_populates="books"
    )
    shelves = db.relationship("Shelf", secondary=book_shelves, back_populates="books")

    # One catalog record currently maps to one sellable copy. The FK lives on
    # Inventory (see below) so this could become one-to-many later without
    # touching the Book table.
    inventory = db.relationship(
        "Inventory",
        back_populates="book",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # --- Convenience accessors ------------------------------------------
    # Templates/routes work against a single "book" object, so these proxy
    # through to the linked Inventory row without duplicating columns.

    @property
    def price(self):
        return self.inventory.price if self.inventory else None

    @property
    def stock(self):
        return self.inventory.stock if self.inventory else 0

    @property
    def condition(self):
        return self.inventory.condition if self.inventory else None

    @property
    def is_featured(self):
        return bool(self.inventory and self.inventory.is_featured)

    @property
    def in_stock(self):
        return bool(self.inventory and self.inventory.stock > 0)

    @property
    def date_added(self):
        return self.inventory.date_added if self.inventory else self.created_at

    @property
    def genre(self):
        """Primary category name, for templates that expect a single genre."""
        first = self.categories[0] if self.categories else None
        return first.name if first else ""

    def whatsapp_message(self):
        price = self.price or 0
        return (
            f"Hi! I'd like to order \"{self.title}\" by {self.author} "
            f"(\u20b9{price:,.0f}). Please confirm availability and delivery options."
        )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "isbn": self.isbn,
            "publisher": self.publisher,
            "description": self.description,
            "pages": self.pages,
            "language": self.language,
            "cover_image": self.cover_image,
            "categories": [c.name for c in self.categories],
            "genre": self.genre,
            "shelves": [s.name for s in self.shelves],
            "condition": self.condition,
            "price": self.price,
            "stock": self.stock,
            "is_featured": self.is_featured,
            "in_stock": self.in_stock,
        }

    def __repr__(self):
        return f"<Book {self.title!r}>"


class Inventory(db.Model):
    """The sellable-copy data for a book: price, stock, condition, dates."""

    __tablename__ = "inventory"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(
        db.Integer, db.ForeignKey("books.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    condition = db.Column(db.String(40), nullable=False, default="Good")
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    book = db.relationship("Book", back_populates="inventory")

    __table_args__ = (
        db.CheckConstraint("price >= 0", name="ck_inventory_price_non_negative"),
        db.CheckConstraint("stock >= 0", name="ck_inventory_stock_non_negative"),
        db.CheckConstraint(
            "condition IN ('New', 'Like New', 'Good', 'Fair')",
            name="ck_inventory_condition_valid",
        ),
    )

    @property
    def in_stock(self):
        return self.stock > 0

    def __repr__(self):
        return f"<Inventory book_id={self.book_id} stock={self.stock}>"


class ImportCache(db.Model):
    """Local cache of metadata fetched from external book catalogs.

    Keyed by normalized ISBN (``isbn:<isbn>``) or free-text search
    (``query:<text>``) so repeat lookups -- e.g. re-opening the import
    screen for the same ISBN -- don't re-hit external APIs. ``payload`` is
    JSON: either a single merged metadata dict (ISBN lookups) or a list of
    candidate dicts (free-text search).
    """

    __tablename__ = "import_cache"

    key = db.Column(db.String(255), primary_key=True)
    source = db.Column(db.String(40), nullable=False, default="")
    payload = db.Column(db.Text, nullable=False)
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<ImportCache {self.key!r} via {self.source}>"


class Setting(db.Model):
    """Simple key/value store for site configuration.

    Lets store details (name, tagline, delivery information, WhatsApp number, ...) be
    edited without a code change, while ``config.py`` still supplies the
    defaults used to seed this table on first run.
    """

    __tablename__ = "settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")

    def __repr__(self):
        return f"<Setting {self.key}={self.value!r}>"
