# webapp/app.py
import os
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from deepseek_client import DeepSeekConfig, DeepSeekClient

load_dotenv()

app = FastAPI(title="DeepSeek Web Chat Demo")

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("Missing DEEPSEEK_API_KEY (export it or put in .env)")

client = DeepSeekClient(DeepSeekConfig(api_key=API_KEY))


def trim_messages(messages: List[Dict[str, str]], keep_turns: int) -> List[Dict[str, str]]:
    """保留 system + 最近 keep_turns 轮(user+assistant)"""
    keep_turns = max(1, int(keep_turns))
    max_non_system = keep_turns * 2

    if messages and messages[0].get("role") == "system":
        sys_msg = messages[0]
        non_sys = messages[1:]
        if len(non_sys) > max_non_system:
            non_sys = non_sys[-max_non_system:]
        return [sys_msg] + non_sys
    else:
        if len(messages) > max_non_system:
            return messages[-max_non_system:]
        return messages


class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: str = "deepseek-chat"
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 1200
    keep_turns: int = 20


class ChatResponse(BaseModel):
    content: str
    reasoning_content: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any]


@app.get("/api/models")
def list_models():
    data = client.list_models()
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    return {"models": ids, "raw": data}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    msgs = trim_messages(req.messages, req.keep_turns)

    resp = client.chat(
        msgs,
        model=req.model,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
    )

    msg = resp["choices"][0]["message"]
    return ChatResponse(
        content=msg.get("content", "") or "",
        reasoning_content=msg.get("reasoning_content"),
        usage=resp.get("usage"),
        raw=resp,
    )


# 静态文件：前端页面
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")


@app.get("/")
def home():
    return FileResponse("webapp/static/index.html")
