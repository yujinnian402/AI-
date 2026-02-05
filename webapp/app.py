# webapp/app.py
import os
import hmac
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI,Request,Depends,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from deepseek_client import DeepSeekConfig, DeepSeekClient

load_dotenv()

app = FastAPI(title="Lara's little home")

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASS = os.environ.get("APP_PASS", "")
APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "")
APP_HTTPS_ONLY = os.environ.get("APP_HTTPS_ONLY", "0") == "1"  # Render 上建议=1，本地开发=0

if not API_KEY:
    raise RuntimeError("Missing DEEPSEEK_API_KEY (export it or put in .env)")
if not APP_PASS:
    raise RuntimeError("Missing APP_PASS (set a login password in env)")
if not APP_SECRET_KEY:
    # 没有 secret_key 会导致 session 签名不稳定（重启就全掉线）
    raise RuntimeError("Missing APP_SECRET_KEY (set a random secret in env)")

# Session 中间件：用 cookie 保存登录态
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET_KEY,
    https_only=APP_HTTPS_ONLY,
    same_site="lax",
)

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

def require_login(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user

class LoginRequest(BaseModel):
    username: str
    password: str

class MeResponse(BaseModel):
    logged_in: bool
    user: Optional[str] = None

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

@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    # 常量时间比较，避免时序侧信道（小细节但很“工程”）
    user_ok = hmac.compare_digest(req.username, APP_USER)
    pass_ok = hmac.compare_digest(req.password, APP_PASS)

    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    request.session["user"] = req.username
    return {"ok": True, "user": req.username}

@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}

@app.get("/api/me", response_model=MeResponse)
def me(request: Request):
    user = request.session.get("user")
    return MeResponse(logged_in=bool(user), user=user)


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
