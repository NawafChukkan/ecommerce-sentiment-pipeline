from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from .config import load_settings


@contextmanager
def db_connection() -> Iterator[psycopg.Connection]:
    settings = load_settings()
    connection = psycopg.connect(settings.database_url)
    try:
        yield connection
    finally:
        connection.close()

