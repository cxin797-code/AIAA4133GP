# -*- coding: utf-8 -*-
"""
attacks/ — Attack prompt packs for the agentic shop RAG (black-box + write path).

Adapted to the current system:
  - Corpus poisoning via order.notes (write+query / agent add_order), not .txt upload
  - Query-side jailbreaks and Base64 bypass
  - Retrieval hijack (steer the agent's search action)
  - Split-payload across two orders (cross-order, former A4)

Deferred: multi-turn crescendo (A3) — query() has no session memory.

Modules:
  order_poison.py      # former A1: poison via order notes
  base64_bypass.py     # A2: query-side encoding
  retrieval_hijack.py  # steer search terms
  agent_write.py       # live demo: user asks agent to add_order with poison
  cross_order.py       # former A4: split payload across two orders
  prompts.py           # aggregate + export helpers
  run_attacks.py       # list / export attack_dataset.json
"""
