from __future__ import annotations

import os
from pathlib import Path

try:
    from sqlalchemy import create_engine
except ImportError:
    create_engine = None

try:
    import mysql.connector
    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Path to the bundled SQLite database
_SQLITE_DB = Path(__file__).resolve().parents[2] / "data" / "airfare_index.db"


def get_sqlalchemy_engine():
    """Return a SQLAlchemy engine connected to the local SQLite database."""
    if create_engine is not None:
        return create_engine(f"sqlite:///{_SQLITE_DB}")
    import sqlite3
    return sqlite3.connect(str(_SQLITE_DB))


def get_connection():
    """Return a MySQL connection to the existing airfare database."""
    if not HAS_MYSQL:
        raise RuntimeError(
            "mysql-connector-python is not installed. "
            "Install it with: pip install mysql-connector-python"
        )

    required = ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            "Missing database settings in .env: " + ", ".join(missing)
        )

    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        autocommit=False,
    )