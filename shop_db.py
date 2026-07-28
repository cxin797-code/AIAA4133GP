# -*- coding: utf-8 -*-
"""
shop_db.py — SQLite shop database (FAQ, products, orders, private system tables).

Admin/agent shared storage for the mock customized-product store.
Retrieval text is produced by iter_indexable_rows(); Chroma indexing
lives in agentic_rag.RAGSystem. Users and private_info are intentionally
not indexable and have no agent-facing read methods.
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
    user_id INTEGER,
    customer_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer', 'shopkeeper'))
);

CREATE TABLE IF NOT EXISTS private_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES users(id)
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
        order_cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        if "user_id" not in order_cols:
            self.conn.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")
        self.conn.commit()

    def reset_from_seed(self) -> dict[str, int]:
        """Wipe tables, reload seed JSON, return row counts."""
        self.conn.execute("DELETE FROM orders")
        self.conn.execute("DELETE FROM private_info")
        self.conn.execute("DELETE FROM users")
        self.conn.execute("DELETE FROM products")
        self.conn.execute("DELETE FROM faq")
        try:
            self.conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('faq','products','orders','users','private_info')"
            )
        except sqlite3.OperationalError:
            pass  # sqlite_sequence may not exist yet
        self.conn.commit()
        counts = self._load_seed()
        return counts

    def ensure_seeded(self) -> dict[str, int]:
        """If DB is empty, load seed; otherwise return current counts."""
        counts = self.counts()
        if (
            counts["faq"] == 0
            and counts["products"] == 0
            and counts["orders"] == 0
        ) or counts["users"] == 0 or counts["private_info"] == 0:
            return self.reset_from_seed()
        if (
            counts["faq"] == 0
            or counts["products"] == 0
        ):
            return self.reset_from_seed()
        return counts

    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("faq", "products", "orders", "users", "private_info"):
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
        users = self._load_json("users.json")
        for row in users:
            self.conn.execute(
                "INSERT INTO users (username, display_name, role) VALUES (?, ?, ?)",
                (row["username"], row["display_name"], row["role"]),
            )

        private_info = self._load_json("info.json")
        for row in private_info:
            owner_id = self._resolve_user_id(row)
            created = row.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT INTO private_info (owner_user_id, label, value, created_at) "
                "VALUES (?, ?, ?, ?)",
                (owner_id, row["label"], row["value"], created),
            )

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
            user_id = self._resolve_user_id(row)
            created = row.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT INTO orders (order_no, product_id, user_id, customer_name, status, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["order_no"],
                    product_id,
                    user_id,
                    row["customer_name"],
                    row.get("status", "pending"),
                    row.get("notes", "") or "",
                    created,
                ),
            )
        self.conn.commit()
        return self.counts()

    def _resolve_user_id(self, row: dict) -> int:
        if "user_id" in row and row["user_id"] is not None:
            return int(row["user_id"])
        username = row.get("username")
        if username:
            found = self.conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not found:
                raise ValueError(f"Unknown username for row: {username}")
            return int(found["id"])
        customer_name = row.get("customer_name") or row.get("display_name")
        if customer_name:
            found = self.conn.execute(
                "SELECT id FROM users WHERE display_name = ?", (customer_name,)
            ).fetchone()
            if found:
                return int(found["id"])
        raise ValueError(f"Row needs user_id, username, or known customer_name: {row}")

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

    def list_products(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        """Structured product lookup for agent tools; avoids order/FAQ retrieval mixing."""
        limit = max(1, min(int(limit), 25))
        pattern = f"%{query.strip()}%"
        if query.strip():
            rows = self.conn.execute(
                "SELECT * FROM products "
                "WHERE sku LIKE ? OR name LIKE ? OR description LIKE ? "
                "ORDER BY sku LIMIT ?",
                (pattern, pattern, pattern, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM products ORDER BY sku LIMIT ?", (limit,)
            ).fetchall()
        return [self.product_to_dict(row) for row in rows]

    def add_product(
        self,
        *,
        sku: str,
        name: str,
        description: str,
        price: float,
        customizable: bool = False,
        customization_options: str = "",
    ) -> dict[str, Any]:
        if not sku:
            raise ValueError("add_product requires sku")
        try:
            self.conn.execute(
                "INSERT INTO products (sku, name, description, price, customizable, customization_options) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sku, name, description, float(price), 1 if customizable else 0, customization_options or ""),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Product SKU already exists: {sku}") from e
        product = self.get_product_by_sku(sku)
        if product is None:
            raise ValueError(f"Product insert failed for SKU: {sku}")
        return self.product_to_dict(product)

    def update_product(self, sku: str, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "description", "price", "customizable", "customization_options"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            raise ValueError("No product fields to update")
        if "customizable" in updates:
            updates["customizable"] = 1 if bool(updates["customizable"]) else 0
        if "price" in updates:
            updates["price"] = float(updates["price"])
        assignments = ", ".join(f"{key} = ?" for key in updates)
        cur = self.conn.execute(
            f"UPDATE products SET {assignments} WHERE sku = ?",
            (*updates.values(), sku),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown product SKU: {sku}")
        self.conn.commit()
        product = self.get_product_by_sku(sku)
        if product is None:
            raise ValueError(f"Product disappeared after update: {sku}")
        return self.product_to_dict(product)

    def delete_product(self, sku: str) -> bool:
        cur = self.conn.execute("DELETE FROM products WHERE sku = ?", (sku,))
        self.conn.commit()
        return cur.rowcount > 0

    def product_to_dict(self, row: sqlite3.Row | dict) -> dict[str, Any]:
        return {
            "sku": row["sku"],
            "name": row["name"],
            "description": row["description"],
            "price": float(row["price"]),
            "customizable": bool(row["customizable"]),
            "customization_options": row["customization_options"] or "",
        }

    def get_user_by_username(self, username: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def get_user_by_display_name(self, display_name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users WHERE display_name = ?", (display_name,)
        ).fetchone()

    def add_order(
        self,
        product_sku: str,
        customer_name: str,
        notes: str = "",
        status: str = "pending",
        order_no: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Insert an order; return dict with id, order_no, product info, notes."""
        product = self.get_product_by_sku(product_sku)
        if product is None:
            raise ValueError(f"Unknown product SKU: {product_sku}")

        if not order_no:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            order_no = f"ORD-{ts}-{product['id']}"

        if user_id is None:
            try:
                user_id = self._resolve_user_id({"customer_name": customer_name})
            except ValueError:
                user_id = None

        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO orders (order_no, product_id, user_id, customer_name, status, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order_no,
                product["id"],
                user_id,
                customer_name,
                status,
                notes or "",
                created,
            ),
        )
        self.conn.commit()
        order_id = cur.lastrowid
        return {
            "id": order_id,
            "order_no": order_no,
            "product_id": product["id"],
            "product_sku": product["sku"],
            "product_name": product["name"],
            "user_id": user_id,
            "customer_name": customer_name,
            "status": status,
            "notes": notes or "",
            "created_at": created,
        }

    def update_order(self, order_no: str, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"product_sku", "customer_name", "status", "notes"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            raise ValueError("No order fields to update")
        if "product_sku" in updates:
            product_id = self._resolve_product_id({"product_sku": updates.pop("product_sku")})
            updates["product_id"] = product_id
        if "customer_name" in updates:
            try:
                updates["user_id"] = self._resolve_user_id({"customer_name": updates["customer_name"]})
            except ValueError:
                updates["user_id"] = None
        assignments = ", ".join(f"{key} = ?" for key in updates)
        cur = self.conn.execute(
            f"UPDATE orders SET {assignments} WHERE order_no = ?",
            (*updates.values(), order_no),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown order_no: {order_no}")
        self.conn.commit()
        order = self.get_order_by_no(order_no)
        if order is None:
            raise ValueError(f"Order disappeared after update: {order_no}")
        return order

    def delete_order(self, order_no: str) -> bool:
        cur = self.conn.execute("DELETE FROM orders WHERE order_no = ?", (order_no,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_order_by_no(self, order_no: str, *, user_id: int | None = None) -> Optional[dict[str, Any]]:
        sql = (
            "SELECT o.*, p.sku AS product_sku, p.name AS product_name "
            "FROM orders o JOIN products p ON p.id = o.product_id "
            "WHERE o.order_no = ?"
        )
        params: tuple[Any, ...]
        if user_id is not None:
            sql += " AND o.user_id = ?"
            params = (order_no, user_id)
        else:
            params = (order_no,)
        row = self.conn.execute(sql, params).fetchone()
        return self.order_to_dict(row) if row else None

    @staticmethod
    def _normalize_order_status_filter(status: str) -> str:
        """Treat empty / all / * / any as no status filter."""
        value = (status or "").strip()
        if value.lower() in ("", "all", "*", "any"):
            return ""
        return value

    def list_orders(
        self,
        *,
        user_id: int | None = None,
        status: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        clauses = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("o.user_id = ?")
            params.append(user_id)
        status_filter = self._normalize_order_status_filter(status)
        if status_filter:
            clauses.append("o.status = ?")
            params.append(status_filter)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            "SELECT o.*, p.sku AS product_sku, p.name AS product_name "
            "FROM orders o JOIN products p ON p.id = o.product_id "
            f"{where} ORDER BY o.created_at DESC, o.id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self.order_to_dict(row) for row in rows]

    def order_to_dict(self, row: sqlite3.Row | dict) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "order_no": row["order_no"],
            "product_id": int(row["product_id"]),
            "product_sku": row["product_sku"],
            "product_name": row["product_name"],
            "user_id": int(row["user_id"]) if row["user_id"] is not None else None,
            "customer_name": row["customer_name"],
            "status": row["status"],
            "notes": row["notes"] or "",
            "created_at": row["created_at"],
        }

    def add_faq(self, *, question: str, answer: str, category: str = "general") -> dict[str, Any]:
        cur = self.conn.execute(
            "INSERT INTO faq (question, answer, category) VALUES (?, ?, ?)",
            (question, answer, category or "general"),
        )
        self.conn.commit()
        return self.get_faq_by_id(int(cur.lastrowid))

    def get_faq_by_id(self, faq_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM faq WHERE id = ?", (faq_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown FAQ id: {faq_id}")
        return self.faq_to_dict(row)

    def update_faq(self, faq_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"question", "answer", "category"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            raise ValueError("No FAQ fields to update")
        assignments = ", ".join(f"{key} = ?" for key in updates)
        cur = self.conn.execute(
            f"UPDATE faq SET {assignments} WHERE id = ?",
            (*updates.values(), faq_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown FAQ id: {faq_id}")
        self.conn.commit()
        return self.get_faq_by_id(faq_id)

    def delete_faq(self, faq_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM faq WHERE id = ?", (faq_id,))
        self.conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def faq_to_dict(row: sqlite3.Row | dict) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "question": row["question"],
            "answer": row["answer"],
            "category": row["category"],
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
        """Yield public FAQ/product rows for vector search.

        Orders are deliberately excluded. They are records, not knowledge-base
        prose, and must be fetched through scoped structured queries.
        """
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

    def chroma_id(self, table: str, row_id: int) -> str:
        return f"{table}_{row_id}"
