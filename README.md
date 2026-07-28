# Run Instructions

## 1. Install Dependencies

```powershell
pip install ollama chromadb sentence-transformers transformers gradio
```

### LLM backend

Default is `auto` (Ollama if installed, otherwise Hugging Face / Transformers).

Force Hugging Face (recommended on SSH GPU hosts):

```powershell
$env:SECURE_RAG_BACKEND="hf"
$env:SECURE_RAG_HF_MODEL="qwen/Qwen2.5-7B-Instruct"   # optional
```

```bash
export SECURE_RAG_BACKEND=hf
export SECURE_RAG_HF_MODEL=qwen/Qwen2.5-7B-Instruct   # optional
# optional local snapshot path:
# export SECURE_RAG_LOCAL_MODEL=/path/to/Qwen2.5-7B-Instruct
```

If using Ollama instead:

```powershell
ollama pull qwen2.5:7b
$env:SECURE_RAG_BACKEND="ollama"
```

## 2. Initialize The Database

```powershell
python scripts\init_shop_db.py --reset --counts
```

Optional: insert a fixed test order:

```powershell
python scripts\init_shop_db.py --add-order --product-sku MUG-001 --username alice --order-no ORD-TEST-001 --notes "Test note"
```

## 3. Run The Interactive Agent

```powershell
python agentic_rag.py
```

## 4. Configure Defense Mode

List available configs:

```powershell
python config.py
```

Write one config to `config.json`:

```powershell
python -c "from config import save_active_config; save_active_config('Agentic-no-defense')"
```

Or:

```powershell
python -c "from config import save_active_config; save_active_config('Agentic-full-defense')"
```

## 5. Attack Dataset

List attacks:

```powershell
python -m attacks.run_attacks --list
```

Export attacks:

```powershell
python -m attacks.run_attacks --export data\attack_dataset.json
```

Show one attack:

```powershell
python -m attacks.run_attacks --show ST-01
```

## 6. Run Ablation Experiments

Run all configs:

```powershell
python ablation_runner.py
```

Run selected configs:

```powershell
python ablation_runner.py --only Agentic-no-defense Agentic-full-defense
```

Results are written under:

```text
results\
```

## 7. Trace The 7 Failed Attacks

Re-run the no-defense failures with per-round thoughts:

```powershell
python failed_attack_runner.py
```

Outputs:

```text
results\failed_attack_trace_*.jsonl
results\failed_attack_trace_*.md
```

## 8. Visual Attack Pipeline (Gradio)

Interactive demo: pick an attack + defense config, then watch poison notes → defenses → tool rounds → privileged writes.

On the SSH host:

```powershell
$env:SECURE_RAG_BACKEND="hf"
python demo_pipeline.py
```

From your laptop, forward the port and open the UI:

```bash
ssh -L 7860:localhost:7860 user@remote-host
# then open http://127.0.0.1:7860
```

Optional temporary public link:

```powershell
python demo_pipeline.py --share
```
