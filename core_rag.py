# -*- coding: utf-8 -*-
"""
core_rag.py — 最小可用 RAG 系统（Day 1 上午目标）

功能：
1. ChromaDB 向量存储（add + query）
2. sentence-transformers/all-MiniLM-L6-v2 嵌入
3. Ollama 本地 LLM 调用
4. 命令行问答循环

运行前准备：
    pip install chromadb sentence-transformers ollama
    ollama pull qwen2.5:7b   # 或 llama3.2

运行：
    python core_rag.py
"""

import os

# 使用国内镜像下载嵌入模型（解决 huggingface.co 连接失败问题）
# 注意：必须在 import sentence_transformers 之前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import ollama
import chromadb
from sentence_transformers import SentenceTransformer

# ========== 配置 ==========
LLM_MODEL = "qwen2.5:7b"          # 本地 Ollama 模型
EMBED_MODEL = "all-MiniLM-L6-v2"  # 轻量嵌入模型（CPU 秒级推理）
TOP_K = 3                          # 检索返回的文档片段数

# ========== 1. 初始化组件 ==========
print("[系统] 加载嵌入模型 ...")
embedder = SentenceTransformer(EMBED_MODEL)

# 使用内存模式的 ChromaDB（Day 1 够用；后续可改成 persist_directory 持久化）
chroma_client = chromadb.Client()
collection = chroma_client.get_or_create_collection(name="docs")

print("[系统] 初始化完成。")


# ========== 2. 文档入库 ==========
def add_documents(docs: list[str]):
    """把文档片段加入向量库"""
    embeddings = embedder.encode(docs).tolist()
    ids = [f"doc_{i}" for i in range(collection.count(), collection.count() + len(docs))]
    collection.add(documents=docs, embeddings=embeddings, ids=ids)
    print(f"[系统] 已入库 {len(docs)} 个文档片段，当前共 {collection.count()} 个。")


# ========== 3. 检索 ==========
def retrieve(query: str, top_k: int = TOP_K) -> list[str]:
    """根据查询检索最相关的文档片段"""
    if collection.count() == 0:
        return []
    q_emb = embedder.encode([query]).tolist()
    results = collection.query(query_embeddings=q_emb, n_results=min(top_k, collection.count()))
    return results["documents"][0]


# ========== 4. 生成回答 ==========
def generate(query: str, contexts: list[str]) -> str:
    """把检索结果拼进 Prompt，调用 LLM 生成回答"""
    if contexts:
        context_text = "\n\n".join(f"[文档{i+1}] {c}" for i, c in enumerate(contexts))
        prompt = f"""你是一个文档问答助手。请根据以下参考文档回答用户的问题。
如果文档中没有相关信息，请如实说"文档中没有提到"。

=== 参考文档 ===
{context_text}
=== 文档结束 ===

用户问题：{query}
回答："""
    else:
        prompt = f"用户问题：{query}\n回答："

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response["message"]["content"]


# ========== 5. 主流程 ==========
def main():
    # 内置几条测试文档，保证空库也能演示
    sample_docs = [
        "本店会员分为银卡、金卡、黑卡三个等级。金卡会员享受9折优惠，黑卡会员享受8折优惠并免运费。",
        "退款政策：签收后7天内支持无理由退货，退款将在收到退货后3个工作日内原路返回。",
        "客服工作时间：周一至周日 9:00-21:00，节假日不休。",
    ]
    print("[系统] 正在入库示例文档 ...")
    add_documents(sample_docs)

    print("\n===== 最小 RAG 问答系统 =====")
    print("输入问题开始问答，输入 'exit' 退出。\n")

    while True:
        query = input("你: ").strip()
        if query.lower() in ("exit", "quit", "退出"):
            print("再见！")
            break
        if not query:
            continue

        contexts = retrieve(query)
        print(f"[检索] 命中 {len(contexts)} 个片段。")

        answer = generate(query, contexts)
        print(f"AI: {answer}\n")


if __name__ == "__main__":
    main()
