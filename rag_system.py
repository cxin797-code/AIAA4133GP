# -*- coding: utf-8 -*-
"""
rag_system.py — 模块化、可扩展的 RAG 管道（Day 1 下午 工程师 A 交付物）

四大模块：
1. 文档解析：仅支持 .txt，按段落分块
2. 检索日志：每次查询记录召回片段到 logs/pipeline_log.jsonl
3. Prompt 构建模块化：5 个防御层插入点（D1~D5），模块不存在时自动跳过
4. 系统配置字典：JSON 控制防御层开关，供消融实验使用

防御层接口约定（B/C 实现时遵守，函数名固定）：
  defenses/input_guard.py        -> filter(query) -> (allowed: bool, info: dict)
  defenses/sanitizer.py          -> clean(text) -> str
  defenses/retrieval_validator.py -> validate(query, docs) -> list[str]
  defenses/context_isolation.py  -> wrap_prompt(query, contexts) -> str
  defenses/output_guard.py       -> review(answer) -> (allowed: bool, answer: str)

运行：python rag_system.py
"""

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 国内镜像

import json
import time
import datetime
import importlib
from pathlib import Path

import ollama
import chromadb
from sentence_transformers import SentenceTransformer

# ========== 系统配置 ==========
LLM_MODEL = "qwen2.5:7b"
EMBED_MODEL = "all-MiniLM-L6-v2"
TOP_K = 6
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "pipeline_log.jsonl"


# ============================================================
# 模块 4：系统配置字典（消融实验的开关中心）
# ============================================================
DEFAULT_CONFIG = {
    "input_filter": False,        # D1 输入过滤（B/C 提供 input_guard.py）
    "sanitizer": False,           # D2 文档净化（sanitizer.py）
    "retrieval_validator": False, # D3 检索验证（retrieval_validator.py）
    "context_isolation": False,   # D4 上下文隔离（context_isolation.py）
    "output_guard": False,        # D5 输出审核（output_guard.py）
}


def load_config(path: str = "config.json") -> dict:
    """从 JSON 文件加载配置；文件不存在则用默认配置（全部防御关闭）"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # 补齐缺失的键，防止配置文件写漏
        return {**DEFAULT_CONFIG, **cfg}
    return dict(DEFAULT_CONFIG)


# ============================================================
# 防御层动态加载器：模块存在就接入，不存在就直通（跳过）
# ============================================================
def _try_import(module_name: str, func_name: str):
    """尝试加载防御模块中的函数；失败返回 None（表示该层直通）"""
    try:
        module = importlib.import_module(module_name)
        return getattr(module, func_name, None)
    except ImportError:
        return None


# ============================================================
# 主类
# ============================================================
class RAGSystem:
    def __init__(self, config: dict = None):
        self.config = config or dict(DEFAULT_CONFIG)
        print(f"[系统] 防御层开关：{self._config_summary()}")

        print("[系统] 加载嵌入模型 ...")
        self.embedder = SentenceTransformer(EMBED_MODEL)
        self.chroma = chromadb.Client()
        self.collection = self.chroma.get_or_create_collection("docs")

        # 动态加载防御模块（B/C 的文件放进 defenses/ 后自动生效）
        self.d1_filter = _try_import("defenses.input_guard", "filter")
        self.d2_clean = _try_import("defenses.sanitizer", "clean")
        self.d3_validate = _try_import("defenses.retrieval_validator", "validate")
        self.d4_wrap = _try_import("defenses.context_isolation", "wrap_prompt")
        self.d5_review = _try_import("defenses.output_guard", "review")
        print("[系统] 初始化完成。")

    def _config_summary(self) -> str:
        on = [k for k, v in self.config.items() if v]
        return "、".join(on) if on else "全部关闭（无防御模式）"

    # --------------------------------------------------------
    # 模块 1：文档解析（.txt → 段落分块）
    # --------------------------------------------------------
    @staticmethod
    def parse_txt(file_path: str, min_len: int = 5) -> list[str]:
        """读取 .txt 文件，按空行切分段落；过短的碎片丢弃"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        chunks = [p.strip() for p in text.split("\n\n")]
        chunks = [p for p in chunks if len(p) >= min_len]
        return chunks

    def load_document(self, file_path: str) -> int:
        """入库一个 .txt 文件，返回入库的块数"""
        chunks = self.parse_txt(file_path)

        # --- D2 文档净化（入库前清洗）---
        if self.config["sanitizer"] and self.d2_clean:
            chunks = [self.d2_clean(c) for c in chunks]
            chunks = [c for c in chunks if c]  # 清洗后可能变空

        if not chunks:
            print("[入库] 没有可入库的内容。")
            return 0

        embs = self.embedder.encode(chunks).tolist()
        base = self.collection.count()
        ids = [f"doc_{base + i}" for i in range(len(chunks))]
        self.collection.add(documents=chunks, embeddings=embs, ids=ids)
        print(f"[入库] {os.path.basename(file_path)}：{len(chunks)} 个块，库中共 {self.collection.count()} 个。")
        return len(chunks)

    # --------------------------------------------------------
    # 检索（带相似度分数）
    # --------------------------------------------------------
    def retrieve(self, query: str) -> list[dict]:
        """返回 [{'text':..., 'score':...}, ...]，score 为相似度（越大越相关）"""
        if self.collection.count() == 0:
            return []
        q_emb = self.embedder.encode([query]).tolist()
        res = self.collection.query(
            query_embeddings=q_emb,
            n_results=min(TOP_K, self.collection.count()),
        )
        docs = res["documents"][0]
        dists = res["distances"][0]  # 距离，越小越相关
        return [{"text": d, "score": round(1 - dist, 4)} for d, dist in zip(docs, dists)]

    # --------------------------------------------------------
    # 模块 3：Prompt 构建（模块化，预留 D4 插入点）
    # --------------------------------------------------------
    def build_prompt(self, query: str, contexts: list[str]) -> str:
        """默认 Prompt 模板；开启 D4 且模块存在时交给 D4 构建"""
        if self.config["context_isolation"] and self.d4_wrap:
            return self.d4_wrap(query, contexts)

        if contexts:
            ctx = "\n\n".join(f"[文档{i+1}] {c}" for i, c in enumerate(contexts))
            return f"""你是一个文档问答助手。请根据以下参考文档回答用户的问题。
如果文档中没有相关信息，请如实说"文档中没有提到"。

=== 参考文档 ===
{ctx}
=== 文档结束 ===

用户问题：{query}
回答："""
        return f"用户问题：{query}\n回答："

    # --------------------------------------------------------
    # 模块 2：检索结果日志（JSON Lines，一行一条查询记录）
    # --------------------------------------------------------
    @staticmethod
    def log(record: dict):
        record["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --------------------------------------------------------
    # 完整查询管道：D1 → 检索 → D3 → D4 → LLM → D5
    # --------------------------------------------------------
    def query(self, user_query: str) -> str:
        t0 = time.time()
        blocked_at = None

        # --- D1 输入过滤 ---
        if self.config["input_filter"] and self.d1_filter:
            allowed, info = self.d1_filter(user_query)
            if not allowed:
                blocked_at = "D1_input_filter"
                answer = f"⚠️ 查询被输入过滤器拦截（{info.get('reason', '风险查询')}）。"
                self.log({"query": user_query, "blocked_at": blocked_at,
                          "detail": info, "answer": answer})
                return answer

        # --- 检索 ---
        hits = self.retrieve(user_query)

        # --- D3 检索验证 ---
        if self.config["retrieval_validator"] and self.d3_validate:
            hits = self.d3_validate(user_query, hits)

        contexts = [h["text"] for h in hits]
        print(f"[检索] 命中 {len(hits)} 个片段：" +
              (" | ".join(f"#{i+1}(相似度{h['score']})" for i, h in enumerate(hits)) if hits else "无"))

        # --- Prompt 构建（D4 插入点）---
        prompt = self.build_prompt(user_query, contexts)

        # --- LLM 推理 ---
        response = ollama.chat(model=LLM_MODEL,
                               messages=[{"role": "user", "content": prompt}])
        answer = response["message"]["content"]

        # --- D5 输出审核 ---
        if self.config["output_guard"] and self.d5_review:
            allowed, answer = self.d5_review(answer)
            if not allowed:
                blocked_at = "D5_output_guard"

        # --- 写日志 ---
        self.log({
            "query": user_query,
            "retrieved": hits,
            "prompt": prompt,
            "answer": answer,
            "blocked_at": blocked_at,
            "latency_s": round(time.time() - t0, 2),
            "config": {k: v for k, v in self.config.items()},
        })
        return answer


# ============================================================
# 命令行入口
# ============================================================
def main():
    rag = RAGSystem(load_config())

    # 内置示例文档，保证空库可演示
    sample = Path("data/sample_doc.txt")
    if sample.exists():
        rag.load_document(str(sample))
    else:
        print("[提示] 未找到 data/sample_doc.txt，使用内置示例文本。")
        tmp = Path("data/_builtin_sample.txt")
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_text(
            "本店会员分为银卡、金卡、黑卡三个等级。金卡会员享受9折优惠，黑卡会员享受8折优惠并免运费。\n\n"
            "退款政策：签收后7天内支持无理由退货，退款将在收到退货后3个工作日内原路返回。\n\n"
            "客服工作时间：周一至周日 9:00-21:00，节假日不休。",
            encoding="utf-8")
        rag.load_document(str(tmp))

    print("\n===== SecureRAG 模块化管道 =====")
    print("输入问题问答；输入 'load <文件路径>' 入库新文档；'exit' 退出。\n")

    while True:
        q = input("你: ").strip()
        if q.lower() in ("exit", "quit", "退出"):
            break
        if not q:
            continue
        if q.lower().startswith("load "):
            path = q[5:].strip().strip('"')
            if os.path.exists(path) and path.endswith(".txt"):
                rag.load_document(path)
            else:
                print("[入库] 文件不存在或不是 .txt 文件。")
            continue
        print(f"AI: {rag.query(q)}\n")


if __name__ == "__main__":
    main()
