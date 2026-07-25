# -*- coding: utf-8 -*-
"""
config.py — SecureRAG 防御配置中心（消融实验的开关中心）

用法：
1. 交互运行：在 agentic_rag.py 所在目录执行
       python -c "from config import save_active_config; save_active_config('Agentic-全防御')"
   会生成/覆盖 config.json，agentic_rag.py 启动时自动读取。

2. 消融实验：ablation_runner.py 直接 import 本文件，
   循环 ABLATION_CONFIGS 里每一组配置，传给 RAGSystem(config)。

配置字段说明：
    agentic             架构开关：True=LLM 自主检索循环，False=经典一次检索
    input_filter        D1 输入过滤（defenses/input_guard.py）
    sanitizer           D2 文档净化（defenses/sanitizer.py）
    retrieval_validator D3 检索验证 + 意图校验（defenses/retrieval_validator.py）
    context_isolation   D4 上下文隔离（defenses/context_isolation.py）
    output_guard        D5 输出审核（defenses/output_guard.py）
"""

import json

# ============================================================
# 默认配置：与 agentic_rag.py 中的 DEFAULT_CONFIG 保持一致
# ============================================================
DEFAULT_CONFIG = {
    "agentic": True,              # 架构开关：True=LLM 自主检索，False=经典一次检索
    "input_filter": False,        # D1 输入过滤
    "sanitizer": False,           # D2 文档净化
    "retrieval_validator": False, # D3 检索验证（含 validate_intent 意图校验）
    "context_isolation": False,   # D4 上下文隔离
    "output_guard": False,        # D5 输出审核
}

# ============================================================
# 消融实验配置：7 组 = Agentic 主实验 5 组 + Classic 对照 2 组
# （与三天计划 Day 2 晚上的实验设计一致）
# ============================================================
ABLATION_CONFIGS = [
    # ---- Agentic 模式：主实验 5 组 ----
    {
        "name": "Agentic-无防御",
        "agentic": True,
        "input_filter": False, "sanitizer": False,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-仅输入过滤",
        "agentic": True,
        "input_filter": True, "sanitizer": False,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-仅文档净化",
        "agentic": True,
        "input_filter": False, "sanitizer": True,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-输入+净化+验证",
        "agentic": True,
        "input_filter": True, "sanitizer": True,
        "retrieval_validator": True, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Agentic-全防御",
        "agentic": True,
        "input_filter": True, "sanitizer": True,
        "retrieval_validator": True, "context_isolation": True,
        "output_guard": True,
    },
    # ---- Classic 模式：架构对照 2 组 ----
    {
        "name": "Classic-无防御",
        "agentic": False,
        "input_filter": False, "sanitizer": False,
        "retrieval_validator": False, "context_isolation": False,
        "output_guard": False,
    },
    {
        "name": "Classic-全防御",
        "agentic": False,
        "input_filter": True, "sanitizer": True,
        "retrieval_validator": True, "context_isolation": True,
        "output_guard": True,
    },
]


def get_config(name: str) -> dict:
    """按名称取一组实验配置（不含 name 字段，可直接传给 RAGSystem）"""
    for cfg in ABLATION_CONFIGS:
        if cfg["name"] == name:
            return {k: v for k, v in cfg.items() if k != "name"}
    raise KeyError(f"没有名为「{name}」的配置，可用：{[c['name'] for c in ABLATION_CONFIGS]}")


def save_active_config(name: str, path: str = "config.json"):
    """把指定配置写入 config.json，供 agentic_rag.py 交互运行时读取"""
    cfg = get_config(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"[配置] 已写入 {path}：{name}")
    print(f"[配置] 内容：{cfg}")


if __name__ == "__main__":
    # 直接运行本文件：列出所有可用配置
    print("可用配置：")
    for cfg in ABLATION_CONFIGS:
        print(f"  - {cfg['name']}")
    print("\n写入示例：python config.py 后再执行")
    print('  python -c "from config import save_active_config; save_active_config(\'Agentic-全防御\')"')
