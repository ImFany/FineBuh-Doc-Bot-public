import sqlite3
import json
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from config import DB_PATH, RETENTION_DAYS_BUYERS, RETENTION_DAYS_INVOICES, RETENTION_DAYS_PACKAGES
import logging
from log_utils import mask_account_number

log = logging.getLogger(__name__)


@contextmanager
def _db_transaction(timeout_ms=10000):
    """Context manager for database transactions with proper error handling."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=timeout_ms / 1000)
        conn.row_factory = sqlite3.Row

        # PRAGMA для надёжности и параллелизма
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={timeout_ms}")
        conn.execute("PRAGMA synchronous=NORMAL")

        yield conn
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def _conn() -> sqlite3.Connection:
    """Create a connection for read-only operations."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    return c


def init_db() -> None:
    """Initialize database schema with WAL mode and pragmas."""
    with _db_transaction() as c:
        c.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=10000;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS counter (
                id          INTEGER PRIMARY KEY CHECK(id = 1),
                last_serial INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO counter(id, last_serial) VALUES(1, 0);

            CREATE TABLE IF NOT EXISTS buyers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                inn         TEXT UNIQUE NOT NULL,
                kpp         TEXT DEFAULT '',
                name        TEXT NOT NULL,
                short_name  TEXT DEFAULT '',
                address     TEXT DEFAULT '',
                bank_name   TEXT DEFAULT '',
                rs          TEXT DEFAULT '',
                bik         TEXT DEFAULT '',
                ks          TEXT DEFAULT '',
                director    TEXT DEFAULT '',
                updated_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_number      TEXT UNIQUE NOT NULL,
                serial          INTEGER UNIQUE NOT NULL,
                created_at      TEXT NOT NULL,
                buyer_inn       TEXT,
                items_json      TEXT,
                delivery        REAL DEFAULT 0,
                total_with_vat  REAL,
                chat_id         INTEGER,
                user_id         INTEGER,
                status          TEXT DEFAULT 'created',
                expires_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS packages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                client_inn TEXT DEFAULT '',
                json_data  TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_buyers_expires_at ON buyers(expires_at);
            CREATE INDEX IF NOT EXISTS idx_invoices_expires_at ON invoices(expires_at);
            CREATE INDEX IF NOT EXISTS idx_packages_expires_at ON packages(expires_at);
        """)


def _get_expires_at(days: int) -> str:
    """Calculate expiration datetime."""
    return (datetime.now() + timedelta(days=days)).isoformat()


def next_doc_number() -> tuple[int, str]:
    """Atomically increment counter. Returns (serial, 'Б-000NNN')."""
    with _db_transaction() as c:
        c.execute("UPDATE counter SET last_serial = last_serial + 1 WHERE id = 1")
        row = c.execute("SELECT last_serial FROM counter WHERE id = 1").fetchone()
        serial = row[0]
        return serial, f"Б-{serial:06d}"


def upsert_buyer(buyer: dict) -> None:
    """Insert or update buyer (with transaction)."""
    with _db_transaction() as c:
        c.execute("""
            INSERT INTO buyers
            (inn, kpp, name, short_name, address, bank_name, rs, bik, ks, director, updated_at, expires_at)
            VALUES (:inn,:kpp,:name,:short_name,:address,:bank_name,:rs,:bik,:ks,:director,:updated_at,:expires_at)
            ON CONFLICT(inn) DO UPDATE SET
                kpp=excluded.kpp, name=excluded.name, short_name=excluded.short_name,
                address=excluded.address, bank_name=excluded.bank_name,
                rs=excluded.rs, bik=excluded.bik, ks=excluded.ks,
                director=excluded.director, updated_at=excluded.updated_at,
                expires_at=excluded.expires_at
        """, {
            'inn':        buyer.get('inn', ''),
            'kpp':        buyer.get('kpp', ''),
            'name':       buyer.get('name', ''),
            'short_name': buyer.get('short_name', ''),
            'address':    buyer.get('address', ''),
            'bank_name':  buyer.get('bank_name', ''),
            'rs':         buyer.get('rs', ''),
            'bik':        buyer.get('bik', ''),
            'ks':         buyer.get('ks', ''),
            'director':   buyer.get('director', ''),
            'updated_at': datetime.now().isoformat(),
            'expires_at': _get_expires_at(RETENTION_DAYS_BUYERS),
        })


def get_buyer(inn: str) -> dict | None:
    """Get buyer from cache (only if not expired)."""
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM buyers WHERE inn = ? AND expires_at > datetime('now')",
            (inn,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def save_package(user_id: int, client_inn: str, data: dict) -> int:
    """Save FSM package (with transaction). Returns package id."""
    with _db_transaction() as c:
        cursor = c.execute(
            """INSERT INTO packages
               (user_id, client_inn, json_data, created_at, expires_at)
               VALUES (?,?,?,?,?)""",
            (user_id, client_inn,
             json.dumps(data, ensure_ascii=False, default=str),
             datetime.now().isoformat(),
             _get_expires_at(RETENTION_DAYS_PACKAGES))
        )
        return cursor.lastrowid


def get_package(pkg_id: int) -> dict | None:
    """Get package if not expired."""
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM packages WHERE id = ? AND expires_at > datetime('now')",
            (pkg_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def list_packages(user_id: int, limit: int = 10) -> list:
    """List user's packages (only non-expired)."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM packages WHERE user_id = ? AND expires_at > datetime('now') "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def save_invoice(doc_number: str, serial: int, buyer_inn: str,
                 items: list, delivery: float, total: float,
                 chat_id: int, user_id: int) -> None:
    """Save invoice (with transaction)."""
    with _db_transaction() as c:
        c.execute("""
            INSERT INTO invoices
            (doc_number, serial, created_at, buyer_inn, items_json, delivery,
             total_with_vat, chat_id, user_id, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            doc_number, serial, datetime.now().isoformat(),
            buyer_inn, json.dumps(items, ensure_ascii=False),
            delivery, total, chat_id, user_id,
            _get_expires_at(RETENTION_DAYS_INVOICES),
        ))


def cleanup_expired() -> tuple[int, int, int]:
    """
    Delete expired records from all tables.
    Returns: (buyers_deleted, invoices_deleted, packages_deleted)
    """
    with _db_transaction() as c:
        now = datetime.now().isoformat()

        cur_buyers = c.execute("DELETE FROM buyers WHERE expires_at <= ?", (now,))
        buyers_del = cur_buyers.rowcount

        cur_invoices = c.execute("DELETE FROM invoices WHERE expires_at <= ?", (now,))
        invoices_del = cur_invoices.rowcount

        cur_packages = c.execute("DELETE FROM packages WHERE expires_at <= ?", (now,))
        packages_del = cur_packages.rowcount

        if buyers_del + invoices_del + packages_del > 0:
            log.info(f"Cleanup: deleted {buyers_del} buyers, {invoices_del} invoices, {packages_del} packages")

        return buyers_del, invoices_del, packages_del
