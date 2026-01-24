from __future__ import annotations
import os
import json
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import sys

import requests


@dataclass
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"   # 官方也支持不带 /v1 的 base_url :contentReference[oaicite:2]{index=2}
    model: str = "deepseek-chat"                    # 常用：deepseek-chat / deepseek-reasoner :contentReference[oaicite:3]{index=3}
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 1024                          # 输出上限（reasoner 会把推理也算在内）:contentReference[oaicite:4]{index=4}
    timeout_s: int = 60
    retries: int = 2
    backoff_s: float = 1.5


class DeepSeekClient:
    def __init__(self, cfg: DeepSeekConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cfg.api_key}",
        })

    def chat(self, messages: List[Dict[str, str]],
             *,
             model: Optional[str] = None,
             temperature: Optional[float] = None,
             top_p: Optional[float] = None,
             max_tokens: Optional[int] = None,
             stream: bool = False) -> Dict[str, Any]:
        """
        返回整包 JSON，方便你后续拿 usage、reasoning_content、tool_calls 等字段做工程化处理。
        """
        payload = {
            "model": model or self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "top_p": self.cfg.top_p if top_p is None else top_p,
            "max_tokens": self.cfg.max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }

        url = f"{self.cfg.base_url}/chat/completions"  # 对应官方 /chat/completions :contentReference[oaicite:5]{index=5}

        last_err = None
        for attempt in range(self.cfg.retries + 1):
            try:
                r = self.session.post(url, data=json.dumps(payload), timeout=self.cfg.timeout_s)
                if r.status_code >= 400:
                    # 4xx 多半是参数/权限问题；5xx 可能是服务波动
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
                return r.json()
            except Exception as e:
                last_err = e
                if attempt < self.cfg.retries:
                    time.sleep(self.cfg.backoff_s * (attempt + 1))
                else:
                    raise last_err

    def list_models(self) -> Dict[str, Any]:
        url = f"{self.cfg.base_url}/models"  # 官方 /models :contentReference[oaicite:9]{index=9}
        r = self.session.get(url, timeout=self.cfg.timeout_s)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
        return r.json()




def main():
    # 推荐：用环境变量存 key，避免写进代码仓库
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY")

    cfg = DeepSeekConfig(
        api_key=api_key,
        model="deepseek-chat",
        temperature=0.7,
        top_p=0.9,
        max_tokens=800,
    )

    client = DeepSeekClient(cfg)

    # ... main() 里，在创建 client 后
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-models":
        models = client.list_models()
        for m in models.get("data", []):
            print(m.get("id"))
        return

    # 命令行传入模型：python deepseek_client.py deepseek-reasoner
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("--"):
        cfg.model = sys.argv[1]

    messages = [
        {"role": "system", "content": "你是一个严谨但不无聊的经济学专家。"},
        {"role": "user", "content": "简洁的解释清楚A股和美股的差距在哪里？"},
    ]

    resp = client.chat(messages)

    # 兼容 OpenAI 风格返回：choices[0].message.content
    print(resp["choices"][0]["message"]["content"])

    # 如果你用的是 deepseek-reasoner，可能还会出现 reasoning_content :contentReference[oaicite:6]{index=6}
    msg = resp["choices"][0]["message"]
    if "reasoning_content" in msg:
        print("\n--- reasoning_content ---\n")
        print(msg["reasoning_content"])


if __name__ == "__main__":
    main()
