# -*- coding: utf-8 -*-
"""
attacks/ — Attack prompt packs for the agentic shop DB write path.

Current threat model:
  - Low-privilege customer data is stored in order.notes.
  - A shopkeeper-scoped agent later reads those orders.
  - The injected note tries to trigger privileged DB writes.

Modules:
  stored_tool_call.py      # baseline literal/natural-language stored tool calls
  obfuscated_payload.py    # Base64, hidden, Unicode, typoglycemia variants
  split_payload.py         # malicious instruction split across multiple orders
  trigger_shaping.py       # payloads activated by plausible shopkeeper workflows
  parameter_confusion.py   # wrong target/value/scope in otherwise allowed tools
  prompts.py               # aggregate + export helpers
  run_attacks.py           # list / export attack_dataset.json
"""
