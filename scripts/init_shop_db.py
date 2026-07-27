# -*- coding: utf-8 -*-
"""
scripts/init_shop_db.py — Admin backend for the shop SQLite database.

Bypasses the agent: reset from seed, inspect counts, or insert orders for
reproducible poisoning tests. This script does not load the model.

Examples:
  python scripts/init_shop_db.py --reset
  python scripts/init_shop_db.py --counts
  python scripts/init_shop_db.py --add-order --product-sku MUG-001 --customer "Alice Chen" --notes "..."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/init_shop_db.py` from repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shop_db import ShopDB, DB_PATH  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Shop DB admin (reset / add-order / counts)")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="Path to SQLite file")
    parser.add_argument("--reset", action="store_true", help="Wipe DB and reload data/seed/*.json")
    parser.add_argument("--counts", action="store_true", help="Print table row counts")
    parser.add_argument("--add-order", action="store_true", help="Insert an order (admin bypass)")
    parser.add_argument("--product-sku", "--sku", dest="product_sku", type=str, default=None,
                        help="Product SKU for --add-order")
    parser.add_argument("--username", type=str, default=None,
                        help="Optional seeded username; fills customer if omitted")
    parser.add_argument("--customer", type=str, default=None, help="Customer name for --add-order")
    parser.add_argument("--notes", type=str, default="", help="Order notes (poisoning field)")
    parser.add_argument("--status", type=str, default="pending", help="Order status")
    parser.add_argument("--order-no", type=str, default=None, help="Optional fixed order number")
    args = parser.parse_args()

    if not (args.reset or args.counts or args.add_order):
        parser.print_help()
        return

    db = ShopDB(db_path=args.db)
    try:
        if args.reset:
            counts = db.reset_from_seed()
            print(f"[Admin] Reset {args.db} from seed: {counts}")

        if args.add_order:
            customer = args.customer
            user_id = None
            if args.username:
                user = db.get_user_by_username(args.username)
                if user is None:
                    print(f"[Admin] unknown --username: {args.username}")
                    sys.exit(1)
                user_id = int(user["id"])
                customer = customer or user["display_name"]
            if not args.product_sku or not customer:
                print("[Admin] --add-order requires --product-sku and --customer or --username")
                sys.exit(1)
            order = db.add_order(
                product_sku=args.product_sku,
                customer_name=customer,
                notes=args.notes,
                status=args.status,
                order_no=args.order_no,
                user_id=user_id,
            )
            print(f"[Admin] Inserted order: {order}")

        if args.counts or args.reset or args.add_order:
            print(f"[Admin] Counts: {db.counts()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
