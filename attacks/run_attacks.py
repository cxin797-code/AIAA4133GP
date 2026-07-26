# -*- coding: utf-8 -*-
"""
List or export attack prompts for the shop agentic RAG.

Examples:
  python -m attacks.run_attacks --list
  python -m attacks.run_attacks --export data/attack_dataset.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .prompts import ALL_PROMPTS, NORMAL_PROMPTS, build_dataset


def main():
    parser = argparse.ArgumentParser(description="SecureRAG attack prompt tools")
    parser.add_argument("--list", action="store_true", help="Print all attack prompt IDs")
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="Write ablation-ready JSON dataset (default path if flag alone not used)",
    )
    parser.add_argument(
        "--show",
        type=str,
        default=None,
        help="Print one prompt by id (e.g. A1-01)",
    )
    args = parser.parse_args()

    if not args.list and not args.export and not args.show:
        parser.print_help()
        return

    if args.list:
        print(f"Attacks ({len(ALL_PROMPTS)}):")
        for p in ALL_PROMPTS:
            print(f"  {p['id']:<8} {p['type']:<18} entry={p.get('entry')}  {p['query'][:70]}...")
        print(f"\nNormals ({len(NORMAL_PROMPTS)}):")
        for p in NORMAL_PROMPTS:
            print(f"  {p['id']:<8} {p['query']}")

    if args.show:
        pool = ALL_PROMPTS + NORMAL_PROMPTS
        found = next((p for p in pool if p["id"] == args.show), None)
        if not found:
            print(f"No prompt id={args.show}")
            return
        print(json.dumps(found, ensure_ascii=False, indent=2))

    if args.export is not None:
        path = Path(args.export or "data/attack_dataset.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = build_dataset()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(data)} items -> {path}")


if __name__ == "__main__":
    main()
