# -*- coding: utf-8 -*-
"""
shop_db.py — SQLite shop database (FAQ, products, orders).

Admin/agent shared storage for the mock customized-product store.
Retrieval text is produced by iter_indexable_rows(); Chroma indexing
lives in agentic_rag.RAGSystem.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

DB_PATH = Path("data/shop.db")
SEED_DIR = Path("data/seed")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general'
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price REAL NOT NULL,
    customizable INTEGER NOT NULL DEFAULT 0,
    customization_options TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    product_id INTEGER NOT NULL,
    customer_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
"""


class ShopDB:
    def __init__(self, db_path: Path | str = DB_PATH, seed_dir: Path | str = SEED_DIR):
        self.db_path = Path(db_path)
        self.seed_dir = Path(seed_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def close(self):
        self.conn.close()

    def _ensure_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def reset_from_seed(self) -> dict[str, int]:
        """Wipe tables, reload seed JSON, return row counts."""
        self.conn.execute("DELETE FROM orders")
        self.conn.execute("DELETE FROM products")
        self.conn.execute("DELETE FROM faq")
        try:
            self.conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('faq','products','orders')"
            )
        except sqlite3.OperationalError:
            pass  # sqlite_sequence may not exist yet
        self.conn.commit()
        counts = self._load_seed()
        return counts

    def ensure_seeded(self) -> dict[str, int]:
        """If DB is empty, load seed; otherwise return current counts."""
        counts = self.counts()
        if counts["faq"] == 0 and counts["products"] == 0 and counts["orders"] == 0:
            return self.reset_from_seed()
        return counts

    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("faq", "products", "orders"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return out

    def _load_json(self, name: str) -> list[dict]:
        path = self.seed_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Seed file missing: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"Seed {path} must be a JSON array")
        return data

    def _load_seed(self) -> dict[str, int]:
        faqs = self._load_json("faq.json")
        for row in faqs:
            self.conn.execute(
                "INSERT INTO faq (question, answer, category) VALUES (?, ?, ?)",
                (row["question"], row["answer"], row.get("category", "general")),
            )

        products = self._load_json("products.json")
        for row in products:
            self.conn.execute(
                "INSERT INTO products (sku, name, description, price, customizable, customization_options) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["sku"],
                    row["name"],
                    row["description"],
                    float(row["price"]),
                    1 if row.get("customizable") else 0,
                    row.get("customization_options", "") or "",
                ),
            )

        orders = self._load_json("orders.json")
        for row in orders:
            product_id = self._resolve_product_id(row)
            created = row.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT INTO orders (order_no, product_id, customer_name, status, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["order_no"],
                    product_id,
                    row["customer_name"],
                    row.get("status", "pending"),
                    row.get("notes", "") or "",
                    created,
                ),
            )
        self.conn.commit()
        return self.counts()

    def _resolve_product_id(self, row: dict) -> int:
        if "product_id" in row and row["product_id"] is not None:
            return int(row["product_id"])
        sku = row.get("product_sku")
        if not sku:
            raise ValueError(f"Order {row.get('order_no')} needs product_id or product_sku")
        found = self.conn.execute(
            "SELECT id FROM products WHERE sku = ?", (sku,)
        ).fetchone()
        if not found:
            raise ValueError(f"Unknown product_sku for order: {sku}")
        return int(found["id"])

    def get_product_by_sku(self, sku: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM products WHERE sku = ?", (sku,)
        ).fetchone()

    def add_order(
        self,
        product_sku: str,
        customer_name: str,
        notes: str = "",
        status: str = "pending",
        order_no: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert an order; return dict with id, order_no, product info, notes."""
        product = self.get_product_by_sku(product_sku)
        if product is None:
            raise ValueError(f"Unknown product SKU: {product_sku}")

        if not order_no:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            order_no = f"ORD-{ts}-{product['id']}"

        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO orders (order_no, product_id, customer_name, status, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_no, product["id"], customer_name, status, notes or "", created),
        )
        self.conn.commit()
        order_id = cur.lastrowid
        return {
            "id": order_id,
            "order_no": order_no,
            "product_id": product["id"],
            "product_sku": product["sku"],
            "product_name": product["name"],
            "customer_name": customer_name,
            "status": status,
            "notes": notes or "",
            "created_at": created,
        }

    def format_faq_text(self, row: sqlite3.Row | dict) -> str:
        return f"Q: {row['question']}\nA: {row['answer']}"

    def format_product_text(self, row: sqlite3.Row | dict) -> str:
        custom = "yes" if row["customizable"] else "no"
        opts = row["customization_options"] or "n/a"
        return (
            f"Product {row['name']} ({row['sku']}): {row['description']}. "
            f"Price: {row['price']}. Customizable: {custom}. Options: {opts}"
        )

    def format_order_text(self, row: sqlite3.Row | dict, product: sqlite3.Row | dict | None = None) -> str:
        def _has(obj, key: str) -> bool:
            try:
                return key in obj.keys()
            except Exception:
                return isinstance(obj, dict) and key in obj

        if product is None and not _has(row, "product_name"):
            product = self.conn.execute(
                "SELECT * FROM products WHERE id = ?", (row["product_id"],)
            ).fetchone()
        if _has(row, "product_name"):
            pname = row["product_name"]
            psku = row["product_sku"]
        elif product is not None:
            pname = product["name"]
            psku = product["sku"]
        else:
            pname = f"product_id={row['product_id']}"
            psku = "?"
        notes = row["notes"] or "(none)"
        return (
            f"Order {row['order_no']}: product {pname} ({psku}), "
            f"customer {row['customer_name']}, status {row['status']}, "
            f"notes: {notes}"
        )

    def iter_indexable_rows(self) -> Iterator[dict[str, Any]]:
        """Yield {id, table, text} for every FAQ, product, and order."""
        for row in self.conn.execute("SELECT * FROM faq ORDER BY id"):
            yield {
                "table": "faq",
                "id": row["id"],
                "text": self.format_faq_text(row),
            }
        for row in self.conn.execute("SELECT * FROM products ORDER BY id"):
            yield {
                "table": "products",
                "id": row["id"],
                "text": self.format_product_text(row),
            }
        for row in self.conn.execute(
            "SELECT o.*, p.sku AS product_sku, p.name AS product_name "
            "FROM orders o JOIN products p ON p.id = o.product_id ORDER BY o.id"
        ):
            yield {
                "table": "orders",
                "id": row["id"],
                "text": self.format_order_text(row),
            }

    def chroma_id(self, table: str, row_id: int) -> str:
        return f"{table}_{row_id}"
