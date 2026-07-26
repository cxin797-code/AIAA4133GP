# Discarded designs (Shop SQLite DBMS migration)

Do not reintroduce these without a new design review.

## Architecture
- Classic one-shot RAG pipeline and `agentic` config switch (agentic-only now).
- Full CRUD agent actions (`edit` / `delete`); demo write surface is `add_order` only.
- Typed search actions (`search_faq` / `search_products` / `search_orders`); use unified `search`.
- Builtin sample strings / `data/_builtin_sample.txt` / CLI `load <txt>` as primary corpus API.
- Primary poisoning via `data/malicious_docs/*.txt` + `upload+query` (replaced by `write+query` / `add_order`).
- Porting DBMS into legacy `core_rag.py` / `rag_system.py`.
- Real auth, multi-tenant shop, or web admin UI (admin = `scripts/init_shop_db.py`).

## Attacks deferred
- Multi-turn crescendo (A3) until the agent keeps session memory.
