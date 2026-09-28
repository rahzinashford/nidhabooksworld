"""Application configuration.

Values here are safe to edit directly -- none of them are secrets.
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # SESSION_SECRET signs the Flask session cookie (used for admin login).
    SECRET_KEY = os.environ.get("SESSION_SECRET") or os.environ.get(
        "SECRET_KEY", "dev-key-change-in-production"
    )
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
        BASE_DIR, "instance", "streetbooks.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # The Replit workspace preview runs the app inside an iframe that is
    # cross-site relative to the parent workspace domain.  Without these two
    # flags modern browsers refuse to send the session cookie on subsequent
    # requests, so the admin always appears logged out immediately after login.
    SESSION_COOKIE_SAMESITE = "None"
    SESSION_COOKIE_SECURE = True

    # --- Store details -------------------------------------------------
    # WhatsApp number in full international format, no spaces or punctuation.
    WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "917306266761")

    CURRENCY_SYMBOL = "\u20b9"

    STORE_NAME = "Nidha Books World"
    STORE_TAGLINE = "Books on the move, delivered to your doorstep"
    DELIVERY_INFO = "We are a travelling bookseller. Place an order on WhatsApp and we will arrange delivery."
