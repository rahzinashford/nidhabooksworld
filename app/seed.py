"""Seed the database with starter inventory, categories, shelves, and
settings on first run.
"""

from app import db
from app.models import Book, Category, Inventory, Setting, Shelf

COVER = "images/covers/cover-{:02d}.jpg"

SHELVES = [
    {"name": "Featured", "slug": "featured", "description": "Hand-picked favorites from the collection."},
    {"name": "Just Arrived", "slug": "just-arrived", "description": "The newest additions to the collection."},
]

BOOKS = [
    {
        "title": "The Weight of Rain",
        "author": "Elena Marsh",
        "genre": "Literary Fiction",
        "condition": "Good",
        "price": 150,
        "cover": 1,
        "featured": True,
        "stock": 2,
        "isbn": "9780143423891",
        "publisher": "Harborlight Press",
        "pages": 312,
        "language": "English",
        "description": (
            "A quiet, aching novel about a family reassembling itself after "
            "loss, set along a rain-soaked coastline. Foxed pages, a firm "
            "spine, and a previous owner's pencil notes in the margins."
        ),
    },
    {
        "title": "Letters to a Young Cartographer",
        "author": "Owen Faelan",
        "genre": "Essays",
        "condition": "Like New",
        "price": 220,
        "cover": 2,
        "featured": True,
        "stock": 1,
        "isbn": "9780307946867",
        "publisher": "Meridian & Co.",
        "pages": 168,
        "language": "English",
        "description": (
            "A slim, elegant collection of essays on maps, memory, and the "
            "art of getting lost. Barely read -- the spine still creaks."
        ),
    },
    {
        "title": "The Nine Doors of Midnight",
        "author": "Yusuf Ibarra",
        "genre": "Mystery",
        "condition": "Good",
        "price": 140,
        "cover": 3,
        "featured": True,
        "stock": 3,
        "isbn": "9780199535569",
        "publisher": "Raven's Quill",
        "pages": 384,
        "language": "English",
        "description": (
            "A twisting locked-room mystery set in a crumbling opera house. "
            "Some tanning to the pages, but tight binding and a striking "
            "cover."
        ),
    },
    {
        "title": "Groundwork",
        "author": "Dr. Priya Kanth",
        "genre": "Science",
        "condition": "Fair",
        "price": 90,
        "cover": 4,
        "featured": False,
        "stock": 4,
        "isbn": "9780262035613",
        "publisher": "Fieldstone Books",
        "pages": 256,
        "language": "English",
        "description": (
            "An accessible tour of soil science and the hidden life beneath "
            "our feet. Well-loved copy with a cracked cover corner, fully "
            "readable."
        ),
    },
    {
        "title": "The Salt Orchard",
        "author": "Marguerite Duclos",
        "genre": "Literary Fiction",
        "condition": "New",
        "price": 280,
        "cover": 5,
        "featured": True,
        "stock": 1,
        "isbn": "9780593311827",
        "publisher": "Harborlight Press",
        "pages": 402,
        "language": "English",
        "description": (
            "A lush, unread first edition about three generations of women "
            "tending an orchard by the sea. Dust jacket intact, no creases."
        ),
    },
    {
        "title": "Field Notes on Silence",
        "author": "Aki Morrow",
        "genre": "Poetry",
        "condition": "Like New",
        "price": 160,
        "cover": 6,
        "featured": False,
        "stock": 2,
        "isbn": "9780811221351",
        "publisher": "Quiet Hours Editions",
        "pages": 96,
        "language": "English",
        "description": (
            "Spare, wintry poems about solitude and small kindnesses. "
            "Pages are crisp and the cover is unmarked."
        ),
    },
    {
        "title": "The Clockmaker's Daughter's Ledger",
        "author": "Bertram Solari",
        "genre": "Historical Fiction",
        "condition": "Good",
        "price": 150,
        "cover": 7,
        "featured": True,
        "stock": 2,
        "isbn": "9780143128086",
        "publisher": "Gearwork House",
        "pages": 448,
        "language": "English",
        "description": (
            "A meticulous, gear-turning saga set in a 19th-century watch "
            "shop. Well-read but sturdy, with a previous owner's bookplate."
        ),
    },
    {
        "title": "Small Gods of the Kitchen",
        "author": "Renata Alba",
        "genre": "Essays",
        "condition": "Good",
        "price": 120,
        "cover": 8,
        "featured": False,
        "stock": 3,
        "isbn": "9781616206813",
        "publisher": "Hearth & Table Press",
        "pages": 224,
        "language": "English",
        "description": (
            "Warm, funny essays on cooking, grief, and family recipes "
            "passed hand to hand. Some coffee-ring souvenirs on the cover."
        ),
    },
    {
        "title": "The Long Ferry Home",
        "author": "Callum Reyes",
        "genre": "Mystery",
        "condition": "Fair",
        "price": 80,
        "cover": 9,
        "featured": False,
        "stock": 5,
        "isbn": "9780857524337",
        "publisher": "Foghorn Editions",
        "pages": 288,
        "language": "English",
        "description": (
            "A moody, fog-bound thriller aboard a night ferry. Reading copy "
            "with a soft, worn cover -- perfect for the bus."
        ),
    },
    {
        "title": "An Atlas of Forgotten Rivers",
        "author": "Ines Halvard",
        "genre": "Science",
        "condition": "New",
        "price": 300,
        "cover": 10,
        "featured": True,
        "stock": 1,
        "isbn": "9780500518885",
        "publisher": "Cartographic Society Press",
        "pages": 320,
        "language": "English",
        "description": (
            "A gorgeous, unread hardcover charting rivers that have "
            "vanished from modern maps. Heavy stock, vivid plates."
        ),
    },
    {
        "title": "Everything I Owe the Wind",
        "author": "Halima Voss",
        "genre": "Poetry",
        "condition": "Good",
        "price": 130,
        "cover": 1,
        "featured": False,
        "stock": 2,
        "isbn": "9781555978053",
        "publisher": "Quiet Hours Editions",
        "pages": 112,
        "language": "English",
        "description": (
            "A debut collection about migration and the weather we carry "
            "inside us. Gently used, cover slightly sun-faded."
        ),
    },
    {
        "title": "The Understudy's Almanac",
        "author": "Felix Onwuka",
        "genre": "Historical Fiction",
        "condition": "Like New",
        "price": 190,
        "cover": 3,
        "featured": False,
        "stock": 2,
        "isbn": "9780241344890",
        "publisher": "Gearwork House",
        "pages": 336,
        "language": "English",
        "description": (
            "A theatrical, witty novel following a stagehand who becomes a "
            "reluctant star. Practically untouched -- tight spine, clean "
            "pages."
        ),
    },
]

DEFAULT_SETTINGS = [
    ("store_name", "Nidha Books World"),
    ("store_tagline", "Books on the move, delivered to your doorstep"),
    ("delivery_info", "We are a travelling bookseller. Place an order on WhatsApp and we will arrange delivery."),
    ("whatsapp_number", "917306266761"),
    ("currency_symbol", "\u20b9"),
]


def _slugify(name):
    return name.lower().replace("&", "and").replace("'", "").replace(" ", "-")


def seed_if_empty():
    if Book.query.first() is not None:
        return

    categories_by_name = {}

    def get_category(name):
        category = categories_by_name.get(name)
        if category is None:
            category = Category(name=name, slug=_slugify(name))
            db.session.add(category)
            categories_by_name[name] = category
        return category

    shelves_by_slug = {}
    for entry in SHELVES:
        shelf = Shelf(name=entry["name"], slug=entry["slug"], description=entry["description"])
        db.session.add(shelf)
        shelves_by_slug[entry["slug"]] = shelf

    for index, entry in enumerate(BOOKS):
        book = Book(
            title=entry["title"],
            author=entry["author"],
            isbn=entry["isbn"],
            publisher=entry["publisher"],
            description=entry["description"],
            pages=entry["pages"],
            language=entry["language"],
            cover_image=COVER.format(entry["cover"]),
        )
        book.categories.append(get_category(entry["genre"]))
        book.shelves.append(shelves_by_slug["just-arrived"])
        if entry["featured"]:
            book.shelves.append(shelves_by_slug["featured"])

        book.inventory = Inventory(
            price=entry["price"],
            stock=entry["stock"],
            condition=entry["condition"],
            is_featured=entry["featured"],
        )
        db.session.add(book)

    for key, value in DEFAULT_SETTINGS:
        db.session.add(Setting(key=key, value=value))

    db.session.commit()
