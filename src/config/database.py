from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from sqlalchemy import create_engine

try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

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


# Path to the bundled SQLite database (fallback)
_SQLITE_DB = Path(__file__).resolve().parents[2] / "data" / "airfare_index.db"


def clean_db_url(url: str) -> str:
    """Clean query parameters like pgbouncer=true that psycopg2/SQLAlchemy might reject."""
    if not url:
        return ""
    # Remove unsupported query parameters for psycopg2/SQLAlchemy
    url = url.replace("?pgbouncer=true", "").replace("&pgbouncer=true", "")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def get_db_url() -> str:
    """Return database connection URL from environment or fallback to SQLite."""
    # Direct session URL or pooled transaction URL
    url = os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL")
    if url:
        return clean_db_url(url)

    if os.getenv("DB_HOST") and os.getenv("DB_USER"):
        user = os.getenv("DB_USER")
        password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
        host = os.getenv("DB_HOST")
        port = os.getenv("DB_PORT", "5432")
        dbname = os.getenv("DB_NAME", "postgres")
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    return f"sqlite:///{_SQLITE_DB}"


def get_sqlalchemy_engine():
    """Return a SQLAlchemy engine connected to Supabase Postgres (or fallback SQLite)."""
    db_url = get_db_url()
    if db_url.startswith("sqlite:"):
        return create_engine(db_url)
    return create_engine(db_url, pool_pre_ping=True, pool_recycle=300)


def get_connection():
    """Return a native database connection (PostgreSQL via psycopg2, MySQL, or SQLite)."""
    # 1. PostgreSQL / Supabase
    db_url = clean_db_url(os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL") or "")
    if db_url and HAS_POSTGRES:
        return psycopg2.connect(db_url)

    if os.getenv("DB_HOST") and HAS_POSTGRES:
        return psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            dbname=os.getenv("DB_NAME", "postgres"),
        )

    # 2. MySQL fallback if configured
    if HAS_MYSQL and os.getenv("MYSQL_HOST") and os.getenv("MYSQL_USER"):
        return mysql.connector.connect(
            host=os.environ["MYSQL_HOST"],
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.environ["MYSQL_USER"],
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "airfare"),
            autocommit=False,
        )

    # 3. SQLite fallback
    import sqlite3
    return sqlite3.connect(str(_SQLITE_DB))