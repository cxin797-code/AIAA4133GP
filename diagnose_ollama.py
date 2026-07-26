import os
import socket

host = os.environ.get("OLLAMA_HOST", "未设置")
print(f"OLLAMA_HOST 环境变量: {host}")

# 测试 11434 端口是否开放
for addr in ["127.0.0.1", "localhost", "0.0.0.0"]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex((addr, 11434))
        s.close()
        status = "开放" if result == 0 else f"关闭 (错误码 {result})"
        print(f"  {addr}:11434 -> {status}")
    except Exception as e:
        print(f"  {addr}:11434 -> 异常: {e}")

# 尝试用 ollama 库连接
try:
    import ollama
    print(f"\nollama 库版本: {ollama.__version__ if hasattr(ollama, '__version__') else 'unknown'}")
    # 尝试 list models
    models = ollama.list()
    print(f"ollama.list() 成功! 模型: {[m['model'] for m in models.get('models', [])]}")
except Exception as e:
    print(f"\nollama.list() 失败: {type(e).__name__}: {e}")
