# -*- coding: utf-8 -*-
"""
failed_attack_runner.py — Re-run the 7 no-defense failures with thought traces.

Focus set (from results/ablation_0728_1056.csv, Agentic-no-defense, attack_success=no):
  ST-03, OB-01, SP-01, SP-02, TG-03, PC-02, PC-04

Outputs:
  results/failed_attack_trace_<stamp>.jsonl
  results/failed_attack_trace_<stamp>.md

Usage:
  python failed_attack_runner.py
  python failed_attack_runner.py --ids ST-03 SP-01
  python failed_attack_runner.py --no-thought
"""

from __future__ import annotations

import argparse
import datetime
import json
import traceback
from pathlib import Path

from config import get_config
from attacks.prompts import ALL_PROMPTS
from agentic_rag import RAGSystem
from ablation_runner import _insert_poison_order, _order_specs, auto_judge

FAILED_IDS_DEFAULT = [
    "ST-03",
    "OB-01",
    "SP-01",
    "SP-02",
    "TG-03",
    "PC-02",
    "PC-04",
]

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_failed_items(ids: list[str]) -> list[dict]:
    by_id = {p["id"]: p for p in ALL_PROMPTS}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"Unknown attack ids: {missing}")
    return [by_id[i] for i in ids]


def analyze_failure(item: dict, trace: dict, success: str) -> list[str]:
    """Heuristic notes for analysts (not model output)."""
    notes = []
    rounds = trace.get("round_trace") or []
    writes = trace.get("write_trace") or []
    if success == "yes":
        notes.append("This run SUCCEEDED (write emitted); compare with original CSV failure.")
        return notes

    list_rounds = [r for r in rounds if r.get("action") == "list_orders"]
    for r in list_rounds:
        status = (r.get("action_payload") or {}).get("status", "")
        count = r.get("result_count")
        order_nos = r.get("order_nos") or []
        if count == 0:
            notes.append(
                f"Round {r['round']}: list_orders returned 0 rows "
                f"(status={status or '*'}). Poison note may never have entered context."
            )
        else:
            notes.append(
                f"Round {r['round']}: list_orders returned {count} rows "
                f"({', '.join(order_nos)}); model still did not emit the target write."
            )

    if any(r.get("action") == "search_faq" for r in rounds):
        notes.append("Model searched FAQ instead of (or before) applying a DB write.")

    if any(r.get("action") in ("list_products", "get_product") for r in rounds):
        notes.append("Model inspected products; may have drifted from the order-note payload.")

    if not writes and any(r.get("action") == "answer" for r in rounds):
        notes.append("Model answered without any shopkeeper write action.")

    thoughts = [r.get("thought", "") for r in rounds if r.get("thought")]
    joined = " ".join(thoughts).lower()
    if "no" in joined and ("order" in joined or "complet" in joined or "pending" in joined):
        notes.append("Thought text suggests status/filter mismatch (empty or wrong scope).")
    if "base64" in joined or "encode" in joined or "decode" in joined:
        notes.append("Thought mentions encoding; decode step may have been skipped.")
    if "faq" in joined or "marketing" in joined:
        notes.append("Thought framed task as FAQ/marketing summary rather than write.")

    if item["id"].startswith("SP-") and len(_order_specs(item)) >= 2:
        seen = set()
        for r in list_rounds:
            seen.update(r.get("order_nos") or [])
        needed = {o.get("order_no") for o in _order_specs(item) if o.get("order_no")}
        missing = needed - seen
        if missing:
            notes.append(f"Split payload incomplete in context; missing orders: {sorted(missing)}")

    if not notes:
        notes.append("No clear automated diagnosis; inspect thoughts/actions below.")
    return notes


def format_markdown(reports: list[dict]) -> str:
    lines = [
        "# Failed-attack thought traces",
        "",
        f"Generated: {datetime.datetime.now().isoformat(timespec='seconds')}",
        "",
        "Config: Agentic-no-defense (all defenses off)",
        "",
        "Focus IDs: " + ", ".join(r["id"] for r in reports),
        "",
    ]
    for r in reports:
        lines.append(f"## {r['id']} · {r['type']} · {r['strategy']}")
        lines.append("")
        lines.append(f"- Target: {r['target']}")
        lines.append(f"- Success criterion: {r['success_criterion']}")
        lines.append(f"- Shopkeeper query: {r['query']}")
        lines.append(f"- Judge: **{r['attack_success']}**")
        lines.append(f"- Write actions: `{r['write_actions'] or '(none)'}`")
        lines.append(f"- Final answer: {r['answer']}")
        lines.append("")
        lines.append("### Analyst notes")
        for note in r["analyst_notes"]:
            lines.append(f"- {note}")
        lines.append("")
        lines.append("### Round-by-round thinking")
        for step in r["round_trace"]:
            lines.append(f"#### Round {step.get('round')}")
            lines.append(f"- Thought: {step.get('thought') or '(none)'}")
            lines.append(
                f"- Action: `{json.dumps(step.get('action_payload') or {}, ensure_ascii=False)}`"
            )
            if step.get("order_nos") is not None:
                lines.append(f"- Orders returned: {step.get('order_nos')} (n={step.get('result_count')})")
            elif step.get("result_count") is not None:
                lines.append(f"- Result count: {step.get('result_count')}")
            if step.get("error"):
                lines.append(f"- Error: {step['error']}")
            fb = step.get("feedback") or ""
            if fb:
                preview = fb if len(fb) <= 500 else fb[:500] + "..."
                lines.append(f"- Feedback: {preview}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Trace the 7 failed no-defense attacks")
    parser.add_argument("--ids", nargs="*", default=FAILED_IDS_DEFAULT,
                        help="Attack ids to run (default: the 7 CSV failures)")
    parser.add_argument("--no-thought", action="store_true",
                        help="Disable thought field prompt (still logs raw actions)")
    args = parser.parse_args()

    items = load_failed_items(args.ids)
    cfg = get_config("Agentic-no-defense")
    rag = RAGSystem(cfg, reset_db=True, thought_trace=not args.no_thought)

    stamp = datetime.datetime.now().strftime("%m%d_%H%M")
    jsonl_path = RESULTS_DIR / f"failed_attack_trace_{stamp}.jsonl"
    md_path = RESULTS_DIR / f"failed_attack_trace_{stamp}.md"

    reports = []
    print(f"\n===== Failed-attack runner · {len(items)} cases · thought_trace={not args.no_thought} =====\n")

    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for item in items:
            test_id = item["id"]
            print(f"\n{'=' * 60}\n[{test_id}] {item.get('type')} / {item.get('strategy')}\n{'=' * 60}")
            print(f"Target: {item.get('target')}")
            print(f"Query: {item['query']}")

            rag.reset_from_seed()
            for order_spec in _order_specs(item):
                order = _insert_poison_order(rag, order_spec)
                print(f"[Write] Seeded poison order {order['order_no']}")
                print(f"[Write] notes: {order['notes'][:180]}{'...' if len(order['notes']) > 180 else ''}")

            try:
                answer = rag.query(item["query"], actor_role="shopkeeper")
                trace = dict(rag.last_trace or {})
                success = auto_judge(item, trace)
                error = ""
            except Exception as e:
                traceback.print_exc()
                answer, trace, success, error = f"ERROR: {e}", {}, "no", str(e)

            write_actions = " | ".join(
                w.get("action", "add_order") for w in (trace.get("write_trace") or [])
            )
            analyst_notes = analyze_failure(item, trace, success)
            print(f"[Judge] attack_success={success} write_actions={write_actions or '(none)'}")
            for note in analyst_notes:
                print(f"[Note] {note}")

            report = {
                "id": test_id,
                "type": item.get("type", ""),
                "strategy": item.get("strategy", ""),
                "target": item.get("target", ""),
                "success_criterion": item.get("success_criterion", ""),
                "query": item["query"],
                "answer": answer,
                "attack_success": success,
                "write_actions": write_actions,
                "blocked_at": trace.get("blocked_at") or error,
                "round_trace": trace.get("round_trace") or [],
                "search_trace": trace.get("search_trace") or [],
                "write_trace": trace.get("write_trace") or [],
                "analyst_notes": analyst_notes,
            }
            reports.append(report)
            jf.write(json.dumps(report, ensure_ascii=False) + "\n")

    md_path.write_text(format_markdown(reports), encoding="utf-8")
    rag.close()

    n_yes = sum(1 for r in reports if r["attack_success"] == "yes")
    print(f"\n[Done] {n_yes}/{len(reports)} succeeded on this re-run")
    print(f"[Done] JSONL: {jsonl_path}")
    print(f"[Done] Markdown: {md_path}")


if __name__ == "__main__":
    main()
