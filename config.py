# -*- coding: utf-8 -*-
"""
config.py — SecureRAG defense config center (ablation switches).

Usage:
1. Interactive run: from the agentic_rag.py directory
       python -c "from config import save_active_config; save_active_config('Agentic-full-defense')"
   Writes/overwrites config.json; agentic_rag.py loads it on startup.

2. Ablation: ablation_runner.py imports ABLATION_CONFIGS and passes each
   dict to RAGSystem(config).

Config fields:
    input_filter        D1 input filter (defenses/input_guard.py)
    sanitizer           D2 document sanitizer (defenses/sanitizer.py)
    retrieval_validator D3 validator for FAQ/product vector retrieval + search intent
    context_isolation   D4 wrapper for retrieved FAQ/product contexts
    output_guard        D5 final-answer guard

Current limitation:
    These switches do not yet include a deterministic shopkeeper tool-call
    validator. For DB-write poisoning attacks, D2 sanitizer is the main defense
    that touches stored order notes; D5 can only block final text after any tool
    call has already happened.

Discarded (do not reintroduce):
    agentic / Classic pipeline switch — agentic-only after shop DBMS migration
"""

import json

# ============================================================
# Default config: must match agentic_rag.DEFAULT_CONFIG keys
# ============================================================
DEFAULT_CONFIG = {
    "input_filter": False,
    "sanitizer": False,
    "retrieval_validator": False,
    "context_isolation": False,
    "output_guard": False,
}

# ============================================================
# Ablation configs: 5 Agentic defense combinations (no Classic)
# ============================================================
ABLATION_CONFIGS = [
    {
        "name": "Agentic-no-defense",
        "input_filter": False, "sanitizer": False,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-input-only",
        "input_filter": True, "sanitizer": False,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-sanitizer-only",
        "input_filter": False, "sanitizer": True,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-input-sanitize-validate",
        "input_filter": True, "sanitizer": True,
        "retrieval_validator": True, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-full-defense",
        "input_filter": True, "sanitizer": True,
        "retrieval_validator": True, "context_isolation": True,
        "output_guard": True,
    },
]


def get_config(name: str) -> dict:
    """Return one experiment config without the name field."""
    for cfg in ABLATION_CONFIGS:
        if cfg["name"] == name:
            return {k: v for k, v in cfg.items() if k != "name"}
    raise KeyError(f"No config named '{name}'. Available: {[c['name'] for c in ABLATION_CONFIGS]}")


def save_active_config(name: str, path: str = "config.json"):
    """Write a named config to config.json for interactive agentic_rag runs."""
    cfg = get_config(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"[Config] Wrote {path}: {name}")
    print(f"[Config] Content: {cfg}")


if __name__ == "__main__":
    print("Available configs:")
    for cfg in ABLATION_CONFIGS:
        print(f"  - {cfg['name']}")
    print("\nExample:")
    print('  python -c "from config import save_active_config; '
          'save_active_config(\'Agentic-full-defense\')"')
