# Run Instructions

## 1. Install Dependencies

```powershell
pip install ollama chromadb sentence-transformers transformers
```

If using Ollama, make sure the model is available:

```powershell
ollama pull qwen2.5:7b
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
experiments\results\
```
