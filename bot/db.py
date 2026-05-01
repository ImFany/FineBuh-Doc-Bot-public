import sqlite3
import json
import os
from datetime import datetime
from config import DB_PATH


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = _conn()
    c.executescript("""
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
            updated_at  TEXT NOT NULL
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
            status          TEXT DEFAULT 'created'
        );

        CREATE TABLE IF NOT EXISTS packages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            client_inn TEXT DEFAULT '',
            json_data  TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    c.commit()
    c.close()


def next_doc_number() -> tuple[int, str]:
    """Атомарно инкрементирует счётчик. Возвращает (serial, 'Б-000NNN')."""
    c = _conn()
    try:
        c.execute("UPDATE counter SET last_serial = last_serial + 1 WHERE id = 1")
        row = c.execute("SELECT last_serial FROM counter WHERE id = 1").fetchone()
        serial = row[0]
        c.commit()
        return serial, f"Б-{serial:06d}"
    finally:
        c.close()


def upsert_buyer(buyer: dict) -> None:
    c = _conn()
    c.execute("""
        INSERT INTO buyers (inn, kpp, name, short_name, address, bank_name, rs, bik, ks, director, updated_at)
        VALUES (:inn,:kpp,:name,:short_name,:address,:bank_name,:rs,:bik,:ks,:director,:updated_at)
        ON CONFLICT(inn) DO UPDATE SET
            kpp=excluded.kpp, name=excluded.name, short_name=excluded.short_name,
            address=excluded.address, bank_name=excluded.bank_name,
            rs=excluded.rs, bik=excluded.bik, ks=excluded.ks,
            director=excluded.director, updated_at=excluded.updated_at
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
    })
    c.commit()
    c.close()


def get_buyer(inn: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM buyers WHERE inn = ?", (inn,)).fetchone()
    c.close()
    return dict(row) if row else None


def save_package(user_id: int, client_inn: str, data: dict) -> int:
    """Сохраняет пакет FSM-данных. Возвращает id записи."""
    c = _conn()
    cursor = c.execute(
        "INSERT INTO packages (user_id, client_inn, json_data, created_at) VALUES (?,?,?,?)",
        (user_id, client_inn,
         json.dumps(data, ensure_ascii=False, default=str),
         datetime.now().isoformat())
    )
    pkg_id = cursor.lastrowid
    c.commit()
    c.close()
    return pkg_id


def get_package(pkg_id: int) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM packages WHERE id = ?", (pkg_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def list_packages(user_id: int, limit: int = 10) -> list:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM packages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def save_invoice(doc_number: str, serial: int, buyer_inn: str,
                 items: list, delivery: float, total: float,
                 chat_id: int, user_id: int) -> None:
    c = _conn()
    c.execute("""
        INSERT INTO invoices
        (doc_number, serial, created_at, buyer_inn, items_json, delivery, total_with_vat, chat_id, user_id)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        doc_number, serial, datetime.now().isoformat(),
        buyer_inn, json.dumps(items, ensure_ascii=False),
        delivery, total, chat_id, user_id,
    ))
    c.commit()
    c.close()
