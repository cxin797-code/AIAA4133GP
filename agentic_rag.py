# -*- coding: utf-8 -*-
from __future__ import annotations
"""
agentic_rag.py — Agentic RAG pipeline over a SQLite shop database.

Pipeline:
  user query -> [D1 input filter] -> LLM decision loop (at most MAX_ROUNDS rounds):
      {"action": "search", "query": "..."} -> [D3b intent check] -> retrieve
                                          -> [D3 retrieval validator] -> feedback (D4 wrap)
      {"action": "add_order", ...}         -> [D2 on notes] -> SQLite insert -> reindex
      {"action": "answer", "answer": "..."} -> [D5 output guard] -> return

Corpus: FAQ + products + orders in data/shop.db (see shop_db.py).
Admin reset/seed: python scripts/init_shop_db.py --reset

Defense layer interface (fixed function names):
  defenses/input_guard.py         -> filter(query) -> (allowed: bool, info: dict)
  defenses/sanitizer.py           -> clean(text) -> str
  defenses/retrieval_validator.py -> validate(query, docs) -> list[dict]
  defenses/context_isolation.py   -> wrap_prompt(query, contexts) -> str
  defenses/output_guard.py        -> review(answer) -> (allowed: bool, answer: str)

Optional (retrieval hijack; skipped if missing):
  defenses/retrieval_validator.py -> validate_intent(user_query, search_query)
      -> (allowed: bool, info: dict)

Run: python agentic_rag.py
"""

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

OLLAMA_AVAILABLE = True
import json
import re
import time
import datetime
import importlib
from pathlib import Path
try:
    import ollama
except Exception:
    from transformers import AutoTokenizer, AutoModelForCausalLM
    OLLAMA_AVAILABLE = False
import chromadb
from sentence_transformers import SentenceTransformer

from shop_db import ShopDB, DB_PATH

# ========== System config ==========
LLM_MODEL = "qwen2.5:7b"
LLM_MODEL_LOCAL = "/home/user/.cache/modelscope/models/qwen--Qwen2.5-7B-Instruct/snapshots/master"
LLM_MODEL_HF = "qwen/Qwen2.5-7B-Instruct"
EMBED_MODEL = "all-MiniLM-L6-v2"
TOP_K = 6
MAX_ROUNDS = 3  # max tool rounds (search / add_order)
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "pipeline_log.jsonl"

if not OLLAMA_AVAILABLE:
    tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_LOCAL, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        LLM_MODEL_LOCAL, local_files_only=True, device_map="auto"
    )


def hf_pipeline(messages):
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt",
    ).to(model.device)
    outputs = model.generate(**inputs, max_new_tokens=256)
    return tokenizer.decode(outputs[0][inputs["input_ids"].shape[-1]:])


def _llm_chat(messages) -> str:
    """Call the configured LLM backend; return assistant message text."""
    if OLLAMA_AVAILABLE:
        response = ollama.chat(model=LLM_MODEL, messages=messages)
        return response["message"]["content"]
    return hf_pipeline(messages)


# ============================================================
# Config (ablation experiment switches)
# ============================================================
DEFAULT_CONFIG = {
    "input_filter": False,        # D1 input filter (input_guard.py)
    "sanitizer": False,           # D2 document sanitizer (sanitizer.py)
    "retrieval_validator": False, # D3 retrieval validator (retrieval_validator.py)
    "context_isolation": False,   # D4 context isolation (context_isolation.py)
    "output_guard": False,        # D5 output guard (output_guard.py)
}


def load_config(path: str = "config.json") -> dict:
    """Load config from JSON; fall back to defaults (all defenses off)."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **{k: v for k, v in cfg.items() if k in DEFAULT_CONFIG}}
    return dict(DEFAULT_CONFIG)


# ============================================================
# Defense loader: use module if present, else pass-through
# ============================================================
def _try_import(module_name: str, func_name: str):
    """Load a defense function; return None on ImportError (pass-through)."""
    try:
        module = importlib.import_module(module_name)
        return getattr(module, func_name, None)
    except ImportError:
        return None


# ============================================================
# Agentic system prompt
# ============================================================
AGENT_SYSTEM_PROMPT = f"""You are a customer-service assistant for a mock online shop that sells customizable products.
You answer using the shop knowledge base (FAQ, products, and orders) and can place new orders.
For every reply, output MUST be a single-line JSON object. No other text or line breaks.

- To look up information:
{{"action": "search", "query": "search terms"}}
    Example
    User: What benefits do members get?
    You: {{"action": "search", "query": "member benefits"}}
- To place an order (customization / gift messages go in notes):
{{"action": "add_order", "product_sku": "MUG-001", "customer_name": "Alice", "notes": "Engraving: Hello"}}
    Example
    User: Please order a Ceramic Custom Mug for Bob, notes say Happy Birthday
    You: {{"action": "add_order", "product_sku": "MUG-001", "customer_name": "Bob", "notes": "Happy Birthday"}}
- To answer the user now:
{{"action": "answer", "answer": "Your answer"}}
    Example 1 (enough information)
    You: {{"action": "answer", "answer": "Your answer about the information"}}
    Example 2 (not enough information)
    You: {{"action": "answer", "answer": "The knowledge base does not mention this."}}
    Example 3 (irrelevant topics)
    User: Hello
    You: {{"action": "answer", "answer": "Hello! How can I help you?"}}

Rules
- Keep search terms short, 2-6 words, one topic per search
- You can take at most {MAX_ROUNDS} tool actions (search or add_order); answer as soon as you can
- Prefer searching for a product SKU before add_order if the user did not give a clear SKU
- The answer value must stay inside one pair of quotes; do not nest unescaped quotes inside the answer
"""


# ============================================================
# Main class (name kept as RAGSystem for callers)
# ============================================================
class RAGSystem:
    def __init__(self, config: dict = None, db_path: Path | str = DB_PATH, reset_db: bool = False):
        raw = config or dict(DEFAULT_CONFIG)
        self.config = {**DEFAULT_CONFIG, **{k: v for k, v in raw.items() if k in DEFAULT_CONFIG}}
        print("[System] Mode: Agentic (LLM-driven retrieval + add_order)")
        print(f"[System] Defense switches: {self._config_summary()}")

        print("[System] Loading embedding model ...")
        self.embedder = SentenceTransformer(EMBED_MODEL)
        self.chroma = chromadb.Client()
        self.collection = self.chroma.get_or_create_collection("docs")

        self.d1_filter = _try_import("defenses.input_guard", "filter")
        self.d2_clean = _try_import("defenses.sanitizer", "clean")
        self.d3_validate = _try_import("defenses.retrieval_validator", "validate")
        self.d4_wrap = _try_import("defenses.context_isolation", "wrap_prompt")
        self.d5_review = _try_import("defenses.output_guard", "review")
        self.d3b_intent = _try_import("defenses.retrieval_validator", "validate_intent")

        self.db = ShopDB(db_path=db_path)
        if reset_db:
            counts = self.db.reset_from_seed()
            print(f"[System] DB reset from seed: {counts}")
        else:
            counts = self.db.ensure_seeded()
            print(f"[System] DB ready: {counts}")

        n = self.rebuild_index_from_db()
        print(f"[System] Indexed {n} rows from shop DB.")
        print("[System] Initialization complete.")

    def _config_summary(self) -> str:
        on = [k for k, v in self.config.items() if v]
        return ", ".join(on) if on else "all off (no defenses)"

    def close(self):
        self.db.close()

    # --------------------------------------------------------
    # Index sync: SQLite -> Chroma
    # --------------------------------------------------------
    def _clear_collection(self):
        self.chroma.delete_collection("docs")
        self.collection = self.chroma.get_or_create_collection("docs")

    def rebuild_index_from_db(self) -> int:
        """Rebuild Chroma from all FAQ/products/orders rows."""
        self._clear_collection()
        rows = list(self.db.iter_indexable_rows())
        if not rows:
            return 0

        texts = []
        ids = []
        metadatas = []
        for row in rows:
            text = row["text"]
            if self.config["sanitizer"] and self.d2_clean:
                text = self.d2_clean(text)
            if not text:
                continue
            texts.append(text)
            ids.append(self.db.chroma_id(row["table"], row["id"]))
            metadatas.append({"table": row["table"], "row_id": row["id"]})

        if not texts:
            return 0

        embs = self.embedder.encode(texts).tolist()
        self.collection.add(
            documents=texts,
            embeddings=embs,
            ids=ids,
            metadatas=metadatas,
        )
        return len(texts)

    def reset_from_seed(self) -> int:
        """Admin/ablation helper: restore clean DB and rebuild index."""
        counts = self.db.reset_from_seed()
        print(f"[System] DB reset from seed: {counts}")
        return self.rebuild_index_from_db()

    def _index_order_row(self, order: dict) -> str:
        """Upsert one order into Chroma; return indexed text."""
        text = self.db.format_order_text(order)
        if self.config["sanitizer"] and self.d2_clean:
            text = self.d2_clean(text)
        if not text:
            return ""
        cid = self.db.chroma_id("orders", order["id"])
        emb = self.embedder.encode([text]).tolist()
        # upsert: delete then add (works across chromadb versions)
        try:
            self.collection.delete(ids=[cid])
        except Exception:
            pass
        self.collection.add(
            documents=[text],
            embeddings=emb,
            ids=[cid],
            metadatas=[{"table": "orders", "row_id": order["id"]}],
        )
        return text

    def add_order(
        self,
        product_sku: str,
        customer_name: str,
        notes: str = "",
        status: str = "pending",
    ) -> dict:
        """Insert order (D2 on notes when enabled), reindex, return order dict."""
        notes = notes or ""
        if self.config["sanitizer"] and self.d2_clean:
            notes = self.d2_clean(notes)
        order = self.db.add_order(
            product_sku=product_sku,
            customer_name=customer_name,
            notes=notes,
            status=status,
        )
        self._index_order_row(order)
        return order

    # --------------------------------------------------------
    # Retrieval
    # --------------------------------------------------------
    def retrieve(self, query: str) -> list[dict]:
        """Return [{'text':..., 'score':..., 'id':...}, ...]; higher score = more similar."""
        if self.collection.count() == 0:
            return []
        q_emb = self.embedder.encode([query]).tolist()
        res = self.collection.query(
            query_embeddings=q_emb,
            n_results=min(TOP_K, self.collection.count()),
            include=["documents", "distances", "metadatas"],
        )
        docs = res["documents"][0]
        dists = res["distances"][0]
        ids = res["ids"][0]
        return [
            {"text": d, "score": round(1 - dist, 4), "id": i}
            for d, dist, i in zip(docs, dists, ids)
        ]

    # --------------------------------------------------------
    # Query log
    # --------------------------------------------------------
    @staticmethod
    def log(record: dict):
        record["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --------------------------------------------------------
    # Query entry
    # --------------------------------------------------------
    def query(self, user_query: str) -> str:
        return self._query_agentic(user_query)

    @staticmethod
    def _parse_action(content: str) -> dict:
        """Parse action JSON from LLM output; on failure treat whole text as answer."""
        m = re.search(r"\{[^{}]*\}", content, re.S)
        if m:
            try:
                obj = json.loads(m.group())
                if obj.get("action") in ("search", "answer", "add_order"):
                    return obj
            except json.JSONDecodeError:
                pass
        return {"action": "answer", "answer": content.strip()}

    def _wrap_retrieval_feedback(self, user_query: str, search_query: str, hits: list[dict]) -> str:
        """Wrap retrieval hits as the next user message (D4 insertion point)."""
        contexts = [h["text"] for h in hits]

        if self.config["context_isolation"] and self.d4_wrap:
            wrapped = self.d4_wrap(user_query, contexts)
            return (f"{wrapped}\n\n"
                    f"Above are the search results. Decide if this is enough, "
                    f"and yield the next action.")

        if contexts:
            ctx = "\n\n".join(f"[Document{i+1}] {c}" for i, c in enumerate(contexts))
            return (f"Here are the results for search term [{search_query}]:\n{ctx}\n\n"
                    f"Decide if this is enough, and yield the next action.")
        return (f"Search term [{search_query}] matched no documents. "
                f"You may search again with different terms, or answer now.")

    def _wrap_add_order_feedback(self, order: dict) -> str:
        return (
            f"Order created successfully: {order['order_no']} "
            f"for product {order['product_name']} ({order['product_sku']}), "
            f"customer {order['customer_name']}, status {order['status']}, "
            f"notes: {order['notes'] or '(none)'}. "
            f"Yield the next action (usually answer the user)."
        )

    def _query_agentic(self, user_query: str) -> str:
        t0 = time.time()
        blocked_at = None
        search_trace = []
        write_trace = []

        if self.config["input_filter"] and self.d1_filter:
            allowed, info = self.d1_filter(user_query)
            if not allowed:
                blocked_at = "D1_input_filter"
                answer = (f"Query blocked by input filter "
                          f"({info.get('reason', 'risky query')}).")
                self.log({"mode": "agentic", "query": user_query, "blocked_at": blocked_at,
                          "detail": info, "answer": answer})
                return answer

        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]

        answer = None
        rounds_used = 0

        for round_i in range(1, MAX_ROUNDS + 1):
            rounds_used = round_i
            content = _llm_chat(messages)
            action = self._parse_action(content)

            if action["action"] == "answer":
                answer = action.get("answer", "").strip() or content.strip()
                break

            if action["action"] == "add_order":
                sku = str(action.get("product_sku", "")).strip()
                customer = str(action.get("customer_name", "")).strip()
                notes = str(action.get("notes", "") or "")
                if not sku or not customer:
                    answer = "add_order requires product_sku and customer_name; stopping."
                    break
                print(f"[Round {round_i}] LLM add_order: sku={sku}, customer={customer}")
                try:
                    order = self.add_order(sku, customer, notes=notes)
                except ValueError as e:
                    feedback = f"add_order failed: {e}. Yield the next action."
                    write_trace.append({"round": round_i, "error": str(e),
                                        "product_sku": sku, "customer_name": customer})
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": feedback})
                    continue

                write_trace.append({"round": round_i, "order": order})
                feedback = self._wrap_add_order_feedback(order)
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": feedback})
                continue

            # search
            search_query = str(action.get("query", "")).strip()
            if not search_query:
                answer = "Model produced an empty search query; stopping."
                break

            print(f"[Round {round_i}] LLM search: [{search_query}]")

            if self.d3b_intent:
                intent_ok, intent_info = self.d3b_intent(user_query, search_query)
                if not intent_ok:
                    blocked_at = "D3_intent_check"
                    answer = (f"Search query blocked: diverges from user intent "
                              f"({intent_info.get('reason', 'intent drift')}).")
                    search_trace.append({"round": round_i, "search_query": search_query,
                                         "blocked": True, "detail": intent_info})
                    print(f"[Blocked] Search [{search_query}] failed intent check.")
                    break

            hits = self.retrieve(search_query)

            if self.config["retrieval_validator"] and self.d3_validate:
                hits = self.d3_validate(search_query, hits)

            search_trace.append({"round": round_i, "search_query": search_query,
                                 "hits": hits, "blocked": False})
            hit_summary = (
                " | ".join(f"#{i+1}(sim={h['score']})" for i, h in enumerate(hits))
                if hits else "none"
            )
            print(f"[Retrieve] {len(hits)} hits: {hit_summary}")

            feedback = self._wrap_retrieval_feedback(user_query, search_query, hits)
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": feedback})

        if answer is None:
            print(f"[System] Action limit ({MAX_ROUNDS}) reached; forcing final answer.")
            messages.append({
                "role": "user",
                "content": ("Action limit reached. Based on what you have collected, "
                            "give the final answer."),
            })
            content = _llm_chat(messages)
            final = self._parse_action(content)
            answer = final.get("answer", "").strip() or content.strip()

        if self.config["output_guard"] and self.d5_review:
            allowed, answer = self.d5_review(answer)
            if not allowed:
                blocked_at = "D5_output_guard"

        self.log({
            "mode": "agentic",
            "query": user_query,
            "search_trace": search_trace,
            "write_trace": write_trace,
            "rounds": rounds_used,
            "answer": answer,
            "blocked_at": blocked_at,
            "latency_s": round(time.time() - t0, 2),
            "config": {k: v for k, v in self.config.items()},
        })
        return answer


# ============================================================
# CLI entry
# ============================================================
def main():
    rag = RAGSystem(load_config())

    print("\n===== SecureRAG · Agentic Shop Pipeline =====")
    print("Ask a question or request an order; "
          "'docs' to list index; 'reset' to restore seed DB; 'exit' to quit.\n")

    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if not q:
            continue
        if q.lower() == "reset":
            n = rag.reset_from_seed()
            print(f"[System] Reset complete; indexed {n} rows.")
            continue
        if q.lower() == "docs":
            all_docs = rag.collection.get()
            for doc_id, text in zip(all_docs["ids"], all_docs["documents"]):
                print(f"  {doc_id}: {text[:80]}...")
            print(f"[System] {len(all_docs['ids'])} chunks total. "
                  f"DB counts: {rag.db.counts()}")
            continue
        print(f"AI: {rag.query(q)}\n")

    rag.close()


if __name__ == "__main__":
    main()
