"""Book registry lookup and authenticated catalog for Read Serene."""
import os
import re
import hmac
import hashlib
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pymysql
from flask import request, jsonify
from google.auth.transport.requests import AuthorizedSession

LEGACY_DOCUMENT = "1ubt637f0K87_Och3Pin9GbJM7w6wzf3M2RCmHbmHgYI"


def connect_db():
    required = ("DB_HOSTA", "DB_USERA", "DB_PASSWORDA", "DB_NAMEA")
    if any(not os.environ.get(key) for key in required):
        raise RuntimeError("Missing database environment variables")
    options = dict(
        host=os.environ["DB_HOSTA"],
        user=os.environ["DB_USERA"],
        password=os.environ["DB_PASSWORDA"],
        database=os.environ["DB_NAMEA"],
        port=int(os.environ.get("DB_PORTA", "3306")),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5, read_timeout=10, write_timeout=10,
    )
    if os.environ.get("DB_SSL_CA"):
        options.update(ssl_ca=os.environ["DB_SSL_CA"],
                       ssl_verify_cert=True, ssl_verify_identity=True)
    return pymysql.connect(**options)


def resolve_document(book_id):
    if not re.fullmatch(r"[A-Za-z0-9]{128}", book_id):
        raise ValueError("Invalid book ID")
    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT document_id FROM book_index WHERE BINARY book_id = %s LIMIT 1",
                (book_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise LookupError("Unknown book")
    return row["document_id"]


def namespace_books(data, document_id):
    # Preserve existing saved audio identifiers for the original document.
    if document_id == LEGACY_DOCUMENT:
        return
    prefix = "doc-" + hashlib.sha256(document_id.encode()).hexdigest()[:16] + "-"
    for book in data.get("books", []):
        book["id"] = prefix + book["id"]
        for chapter in book.get("chapters", []):
            chapter["id"] = prefix + chapter["id"]


def register_book_index(app, credentials_factory):
    @lru_cache(maxsize=512)
    def title_for(document_id, cache_window):
        # Each call gets its own session; no HTTP client is shared across threads.
        credentials = credentials_factory().with_scopes(
            ["https://www.googleapis.com/auth/documents.readonly"]
        )
        with AuthorizedSession(credentials, refresh_timeout=10) as session:
            response = session.get(
                "https://docs.googleapis.com/v1/documents/" + quote(document_id, safe=""),
                params={"fields": "title"}, timeout=(5, 15),
            )
            response.raise_for_status()
            return response.json().get("title") or "Untitled document"

    @app.route("/book-index", methods=["GET"])
    def book_index():
        expected = os.environ.get("RAILWAY_APP_API_KEY", "")
        if not expected:
            return jsonify(error="API key is not configured."), 503
        supplied = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return jsonify(error="Unauthorized."), 401

        try:
            with connect_db() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, document_id, book_id FROM book_index ORDER BY id"
                    )
                    rows = list(cursor.fetchall())
        except Exception:
            app.logger.exception("Could not load book catalog")
            return jsonify(error="Book database unavailable."), 503

        if request.args.get("include_titles") == "1":
            def enrich(row):
                row = dict(row)
                try:
                    row["title"] = title_for(row["document_id"], int(time.time() // 300))
                    row["title_available"] = True
                except Exception:
                    app.logger.warning("Title unavailable for catalog row %s", row["id"])
                    row["title"] = "Document " + str(row["id"])
                    row["title_available"] = False
                return row

            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(enrich, rows))
        response = jsonify(success=True, books=rows)
        response.headers["Cache-Control"] = "no-store"
        return response
