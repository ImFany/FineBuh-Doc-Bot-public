#!/usr/bin/env python3
"""Migrate database schema to add expires_at columns."""
import sqlite3
from datetime import datetime, timedelta
import sys

DB_PATH = "bot/data/bot.db"

def migrate():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Check if columns already exist
        c.execute("PRAGMA table_info(buyers)")
        buyers_cols = [col[1] for col in c.fetchall()]

        # Add expires_at to buyers if not exists
        if 'expires_at' not in buyers_cols:
            print("Adding expires_at to buyers...")
            expires_at = (datetime.now() + timedelta(days=90)).isoformat()
            c.execute(f"ALTER TABLE buyers ADD COLUMN expires_at TEXT DEFAULT '{expires_at}'")
            conn.commit()
            print("[OK] buyers.expires_at added")

        # Add expires_at to invoices if not exists
        c.execute("PRAGMA table_info(invoices)")
        invoices_cols = [col[1] for col in c.fetchall()]
        if 'expires_at' not in invoices_cols:
            print("Adding expires_at to invoices...")
            expires_at = (datetime.now() + timedelta(days=365)).isoformat()
            c.execute(f"ALTER TABLE invoices ADD COLUMN expires_at TEXT DEFAULT '{expires_at}'")
            conn.commit()
            print("[OK] invoices.expires_at added")

        # Add expires_at to packages if not exists
        c.execute("PRAGMA table_info(packages)")
        packages_cols = [col[1] for col in c.fetchall()]
        if 'expires_at' not in packages_cols:
            print("Adding expires_at to packages...")
            expires_at = (datetime.now() + timedelta(days=30)).isoformat()
            c.execute(f"ALTER TABLE packages ADD COLUMN expires_at TEXT DEFAULT '{expires_at}'")
            conn.commit()
            print("[OK] packages.expires_at added")

        # Create indexes if not exist
        c.execute("CREATE INDEX IF NOT EXISTS idx_buyers_expires_at ON buyers(expires_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_invoices_expires_at ON invoices(expires_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_packages_expires_at ON packages(expires_at)")
        conn.commit()

        print("\n[OK] Migration completed successfully!")
        conn.close()
        return True
    except Exception as e:
        print(f"[ERROR] Migration failed: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
