# Embedding 工具模块
# 负责：JWT 鉴权 + 调用智谱 embedding-2 API
import httpx, jwt, time
from typing import List
from configs import ZHIPU_API_KEY, ZHIPU_EMBED_URL, EMBEDDING_MODEL

def generate_token(apikey: str = None, exp_seconds: int = 60) -> str:
    """生成智谱 JWT 鉴权 token，有效期默认 60 秒"""
    key = apikey or ZHIPU_API_KEY
    api_id, secret = key.split(".")
    payload = {
        "api_key": api_id,
        "exp": int(round(time.time() * 1000)) + exp_seconds * 1000,
        "timestamp": int(round(time.time() * 1000)),
    }
    return jwt.encode(payload, secret, algorithm="HS256",
                      headers={"alg": "HS256", "sign_type": "SIGN"})

def embed_texts(texts: List[str]) -> List[List[float]]:
    """调用智谱 embedding-2 API，批量文本 → 向量列表"""
    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    embeddings = []
    with httpx.Client(timeout=30) as client:
        for text in texts:
            resp = client.post(ZHIPU_EMBED_URL, headers=headers,
                               json={"model": EMBEDDING_MODEL, "input": text})
            embeddings.append(resp.json()["data"][0]["embedding"])
    return embeddings
