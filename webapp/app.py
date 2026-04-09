# webapp/app.py
import os
import hmac # python标准库的高级消息认证/安全比较工具
from typing import List, Dict, Any, Optional # Python的类型提示工具,用来标注变量/函数参数/返回值的类型,使Pydantic模型字段更清晰

from dotenv import load_dotenv # 负责把.env文件中的变量加载到环境变量里
# FastAPI建应用,Request取处理对象(含session),Depends依赖注入,HTTPException返回HTTP错误
from fastapi import FastAPI,Request,Depends,HTTPException
from fastapi.responses import FileResponse # FastAPI/Starlette提供的文件响应类
from fastapi.staticfiles import StaticFiles # 用来托管静态资源的工具

from pydantic import BaseModel # PYdantic的基类,用于定义数据模型
from starlette.middleware.sessions import SessionMiddleware # Starlette提供的session中间件
from passlib.context import CryptContext # Passlib提供的密码加密上下文对象
from sqlalchemy.orm import Session # SQLAlchemy的数据库会话类,用于数据库操作

from deepseek_client import DeepSeekConfig, DeepSeekClient

# 数据库连接和用户表模型
# db.py给app.py暴露2个核心能力:数据库总引擎,按请求提供数据库会话的依赖函数以及会话工厂
from webapp.db import engine, get_db, SessionLocal
from webapp.models import Base, User

from authlib.integrations.starlette_client import OAuth # Authlib提供的OAuth客户端工具
from starlette.responses import RedirectResponse

import json # 处理JSON数据,便于Python和JSON(网络传输格式)之间转换
import secrets # 生成安全随机数
from sqlalchemy import text

from webapp.bootstrap import run_lightweight_migrations, ensure_root_user
from webapp.face_auth import face_engine

# 启动时把.env变量载入进os.environ,后续os.environ.get("VAR_NAME")才能拿到key/secret
load_dotenv()

# 创建FastAPI应用实例,后面所有@app.get/post都是往这个实例注册路由
app = FastAPI(title="Lara's little home")

# OAuth注册配置
oauth = OAuth() # 初始化OAuth管理器
# 配置github的授权地址,换token地址,scope(Github采用的是标准的OAuth 2.0授权码模式)
oauth.register(
    name="github",
    client_id=os.environ.get("GITHUB_CLIENT_ID"),
    client_secret=os.environ.get("GITHUB_CLIENT_SECRET"),
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
)
# google用server_metadata_url自动发现OIDC端点,scope包含openid email profile(Google实现了OpenID Connect协议)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

@app.get("/api/auth/{provider}")
async def oauth_login(provider: str, request: Request):
    """
    OAuth传送接口
    1.用户访问/api/auth/github
    2.后端识别provider = "github"
    3.根据provider找到对应OAuth配置
    4.生成Github登录完成后的回调地址
    5.将用户重定向到github授权页面
    """
    # 根据provider自动创建对应的OAuth客户端对象(该client内部包含client_id,client_secret,授权地址等前面oauth.register注册时已经配置好的信息)
    client = oauth.create_client(provider)
    if not client:
        raise HTTPException(status_code=404, detail="Unknown provider")
    # 自动生成OAuth登录成功后的回调地址(通过找到名为oauth_callback的路由然后自动生成该路由对应的URL)
    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    return await client.authorize_redirect(request, redirect_uri)

@app.get("/api/auth/{provider}/callback") # 注册oauth回调路由
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    """
    OAuth回调接口
    1.接收第三方登录回调
    2.用code换token,拿email
    3.在本地数据库中查找或创建用户账号
    4.写入seesion
    5.重定向回首页

    该路由函数传入三个参数,其中request:Request表示当前请求对象(内包含诸多参数以及信息,比如后面要取的token以及code)
    其中第3个参数db: Session = Depends(get_db)表示FastAPI依赖注入,用于给该函数提供一个数据库会话对象db,可以查用户,创建用户,提交事务等
    """
    client = oauth.create_client(provider)
    # 根据第三方回调时带回来的request中的信息(code,state),用code从第三方平台换取access token,并完成必要检验,最终返回一个token字典
    token = await client.authorize_access_token(request)

    # 拿 email
    if provider == "github":
        resp = await client.get("user/emails", token=token) # 调用前面绑定的github API(oauth_register中的api_base_url)获取用户邮箱列表
        emails = resp.json() # 将返回的json格式的HTTP响应转成python的列表/字典
        # 使用生成器表达式筛选邮箱列表中主邮箱+已注册的邮箱地址,next函数表示从生成器里面拿第一个符合条件的结果
        email = next((e["email"] for e in emails if e["primary"] and e["verified"]), None)
    elif provider == "google":
        userinfo = token.get("userinfo")
        email = userinfo.get("email") if userinfo else None

    if not email:
        raise HTTPException(status_code=400, detail="Cannot get email from provider")

    email = email.strip().lower()
    if ROOT_EMAIL and hmac.compare_digest(email, ROOT_EMAIL): # 安全的比较两个字符串是否完全相等的写法
        raise HTTPException(status_code=403, detail="Root account cannot use OAuth login")
    user = db.query(User).filter(User.email == email).first() # User是数据库的表模型
    if not user:
        user = User(email=email, provider=provider, password_hash=None,role="user")
        db.add(user)
        db.commit()
        db.refresh(user)
    # 这里才真正完成网站登录态的建立,在session里记录用户ID(数据库常用主键id,而不是email),后续请求就能通过这个ID识别用户身份(比如/api/me接口就会用到)
    request.session["uid"] = user.id
    return RedirectResponse(url="/")


API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "")
APP_HTTPS_ONLY = os.environ.get("APP_HTTPS_ONLY", "0") == "1"  # Render 上建议=1,本地开发=0
ROOT_EMAIL = os.environ.get("ROOT_EMAIL", "").strip().lower()
ROOT_PASSWORD = os.environ.get("ROOT_PASSWORD", "")

if not API_KEY:
    raise RuntimeError("Missing DEEPSEEK_API_KEY (export it or put in .env)")
if not APP_SECRET_KEY:
    # 没有 secret_key 会导致 session 签名不稳定(重启就全掉线)
    raise RuntimeError("Missing APP_SECRET_KEY (set a random secret in env)")

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto") # 密码哈希配置

# Base是ORM模型的基类,在models.py里定义了User表模型,所以这里会在数据库里创建一个用户表(如果不存在的话)
# metadata是Base类的一个属性,代表数据库结构信息
Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)

# 启动时确保 root 账号存在(仅后端环境变量可创建)
_boot_db = SessionLocal()
try:
    ensure_root_user(
        db=_boot_db,
        pwd=pwd if "pwd" in globals() else CryptContext(schemes=["bcrypt"], deprecated="auto"),
        root_email=ROOT_EMAIL,
        root_password=ROOT_PASSWORD,
    )
finally:
    _boot_db.close()

# Session 中间件:,用 cookie 保存登录态
app.add_middleware(
    SessionMiddleware, # Starlette提供的Session中间件,给FastAPI添加request.session
    secret_key=APP_SECRET_KEY, # Session加密密钥,使cookie在浏览器里,用户无法自己更改
    https_only=APP_HTTPS_ONLY, # 防HTTP抓包
    same_site="lax", # CSRF(跨站请求伪造)防护策略
)

client = DeepSeekClient(DeepSeekConfig(api_key=API_KEY)) # 初始化AI客户端


def trim_messages(messages: List[Dict[str, str]], keep_turns: int) -> List[Dict[str, str]]:
    """
    该裁剪消息函数传入两个参数messages(每个元素为字典的列表)和keep_turns
    返回值是裁剪后的消息列表(类型仍为每个元素为字典的列表)
    
    保留 system + 最近 keep_turns 轮(user+assistant)
    
    why:每次调用模型client.chat(messages)发送的都是整个聊天历史
        若不裁剪token会呈现指数级增长
    """
    keep_turns = max(1, int(keep_turns))
    max_non_system = keep_turns * 2 # 非sysytem信息

    # 如果messages不为空且第一条是sysytem prompt
    if messages and messages[0].get("role") == "system":
        sys_msg = messages[0] # 保留第一条system消息
        non_sys = messages[1:] # 取出后续的所有非system信息
        if len(non_sys) > max_non_system:
            non_sys = non_sys[-max_non_system:] # 该写法代表从后往前取
        return [sys_msg] + non_sys
    else:
        if len(messages) > max_non_system:
            return messages[-max_non_system:]
        return messages

def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    该函数判断当前请求是不是已登录的用户

    传入2个参数,request:Request是当前HTTP请求对象;db自动获取数据库连接;返回User模型对象(数据库里的用户)(成功通过校验)
    """
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = db.query(User).filter(User.id == uid).first() # 查询数据库
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Invalid session")
    return user

def require_root(user: User = Depends(require_user)) -> User:
    if user.role != "root":
        raise HTTPException(status_code=403, detail="Root only")
    return user

# 注册接口请求的数据结构,注意这里的class更多的代表是一种数据模型类的意思,描述数据结构,定义JSON长什么样
# BaseModel来自pydantic库,RegisterReq类继承自BaseModel,获得JSON自动解析,类型校验,自动文档的能力
class RegisterReq(BaseModel):
    email: str
    password: str

# 登录接口请求数据
class LoginReq(BaseModel):
    email: str
    password: str

# 返回给前端的数据结构(用户登录状态)
class MeResp(BaseModel):
    logged_in: bool
    email: Optional[str] = None # 此处Optinal等价于 或
    role: Optional[str] = None

# 聊天接口的请求结构
class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: str = "deepseek-chat"
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 1200
    keep_turns: int = 20

# json转成Python对象
class RootFaceLoginReq(BaseModel):
    email: str
    nonce: str
    image_b64: str


class RootFacePreviewReq(BaseModel):
    email: str
    image_b64: str


class RootFaceEnrollReq(BaseModel):
    image_b64: str


@app.get("/api/models")
def list_models(user: User = Depends(require_user)): 
    """
    函数传入该参数,但不是普通的参数,而是FastAPI的依赖注入,表示调用该函数时会先调用require_user函数
    如果require_user函数成功返回一个User对象,就把这个对象传给user参数
    如果require_user抛出HTTPException(比如用户未登录),就直接返回错误响应,不会继续执行list_models函数
    """
    data = client.list_models()
    # 首先data.get("data",[])从返回结果里面拿取"data"字段,若有就拿到那个列表;若没有就给一个空列表[]
    # for m in data.get("data",[])遍历列表里的每一个模型对象m,拿取它的"id"字段(m.get("id"))
    # 如果有就保留这个id,没有就丢弃该模型;最终把所有保留下来的id组成一个新的列表
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")] # python的列表推导式写法
    return {"models": ids} # 返回一个JSON响应给前端

@app.post("/api/login")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    """
    该函数传入三个参数,req: LoginReq表示请求体里的JSON数据, :contentReference[oaicite:6]{index=6}会自动被FastAPI解析为LoginReq这个Pydantic模型对象
    request:Request代表原始请求对象,可以用来访问session等信息(request.session,也就是当前用户的session)
    db: Session = Depends(get_db)表示依赖注入,会给该函数提供一个数据库会话对象db
    
    """
    email = req.email.strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if not u or not u.password_hash or u.provider != "password":
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not pwd.verify(req.password, u.password_hash): # 验密码,pwd.verify(明文密码,哈希密码)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    request.session["uid"] = u.id # 将当前登录用户的id写进session,后续请求就能通过这个id识别用户身份
    return {"ok": True, "email": u.email} # 登录成功后返回JSON给前端,包含ok和email字段

@app.post("/api/logout")
def logout(request: Request): # 退出登录操作不用查数据库也不用读请求体,故只需传入当前请求对象request作为参数即可
    request.session.clear()
    return {"ok": True} # 告诉前端退出成功

@app.get("/api/me", response_model=MeResp) # 路由装饰器,当前端发GET请求,访问/api/me,就执行下面这个me函数
# respnse_model=MeResp表示该接口最终返回的数据,会按照MeResp这个Pydantic模型的格式来整理/校验(即使返回的是普通字典也会被转换成MeResp对象)
def me(request: Request, db: Session = Depends(get_db)):
    """
    获取当前用户登陆状态以及信息(仅获取状态和信息)
    """
    uid = request.session.get("uid") # 在当前session里面取出键uid对应的值,使用get("uid")而不是直接["uid"]的好处是若没有这个键就返回None,防报错
    if not uid:
        return MeResp(logged_in=False) # 注:此处没有报401,而是返回一个"未登录状态"
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        request.session.clear()
        return MeResp(logged_in=False)
    return MeResp(logged_in=True, email=user.email, role=user.role) # 如果前面的检验都通过了,就给前端返回MeResp这样的信息

@app.post("/api/register") # 当前端用POST请求,访问/api/register,就执行下面这个register()函数
def register(req: RegisterReq, request: Request, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if "@" not in email or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Invalid email or password too short")

    exists = db.query(User).filter(User.email == email).first()
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    u = User(
        email=email,
        password_hash=pwd.hash(req.password),
        provider="password",
        role="user",
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    # 注册完自动登录,进入登录态
    request.session["uid"] = u.id
    return {"ok": True, "email": u.email}

@app.post("/api/chat") # 当前端发送POST请求,到/api/chat,就执行下面这个chat函数
def chat(req: ChatRequest, user: User = Depends(require_user)):
    """
    传入两个参数
    req: ChatRequest是前端发来的聊天请求体,会被解析为ChatRequest对象,里面一般包含messages,model,top_p等参数
    user: User = Depends(require_user)会先调用require_user函数来验证用户身份,只有登录用户才能聊天,认证成功后把当前用户对象传给 user
    
    整个聊天接口流程:
    1.检查是否已登录
    2.拿到前端传来的聊天消息和参数
    3.裁剪历史消息
    4.将消息和参数发给大模型接口
    5.从原始响应里提取回答内容
    6.返回给前端: 正式回答 + 推理内容 + token 用量
    """
    msgs = trim_messages(req.messages, req.keep_turns)

    # client是前面定义好的deepseek客户端实例,chat是deepseek_client.py中的DeepSeekClient类里的实例方法
    resp = client.chat(
        msgs,
        model=req.model,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
    )
    # 从ds给的原始响应里,将真正的那条回复消息提取出来
    msg = resp["choices"][0]["message"] # 兼容OpenAI风格的回复结构,从choices列表里拿第一条,再拿message字段
    # 将原始模型响应,整理成前端需要的格式返回给前端(字典格式)
    return {
        "content": msg.get("content", "") or "",
        "reasoning_content": msg.get("reasoning_content"),
        "usage": resp.get("usage"),
    }

@app.get("/api/root/face/challenge")
def root_face_challenge(request: Request):
    nonce = secrets.token_urlsafe(24) # 生成一个随机字符串(挑战码),长度为24个URL安全的字符,用于人脸登录的防重放攻击
    request.session["root_face_nonce"] = nonce
    return {"nonce": nonce, "ttl_s": 120} # 返回给前端两个东西 nonce(用于做人脸验证的挑战码)和(有效时间)


@app.post("/api/root/face/preview")
def root_face_preview(req: RootFacePreviewReq, db: Session = Depends(get_db)):
    email = req.email.strip().lower()

    if not ROOT_EMAIL or not hmac.compare_digest(email, ROOT_EMAIL):
        raise HTTPException(status_code=403, detail="Face preview is root-only")

    user = db.query(User).filter(User.email == email).first()
    if not user or user.role != "root":
        raise HTTPException(status_code=403, detail="Root account not found")

    row = db.execute(
        text("SELECT embedding_json, threshold FROM user_face_credentials WHERE user_id = :uid"), # :uid是SQL参数占位符,后面将其替换为user.id
        {"uid": user.id}, # 最后的WHERE筛选多加一层限制只查找当前用户的
    ).fetchone() # 从结果中取第一行数据
    if not row:
        raise HTTPException(status_code=400, detail="Root face not enrolled")

    try:
        info = face_engine.extract_face_embedding_and_bbox(req.image_b64)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    emb_saved = json.loads(row[0]) # 将字符串转回Python数组
    threshold = float(row[1] if row[1] is not None else 0.45)
    score = face_engine.cosine_similarity(info["embedding"], emb_saved)

    # 该后端接口最终返回给前端的JSON数据
    return {
        "ok": True,
        "matched": score >= threshold,
        "score": score,
        "threshold": threshold,
        "bbox": info["bbox"],
    }


@app.post("/api/root/face/login")
def root_face_login(req: RootFaceLoginReq, request: Request, db: Session = Depends(get_db)):
    email = req.email.strip().lower()

    # 只允许 ROOT_EMAIL 人脸登录
    if not ROOT_EMAIL or not hmac.compare_digest(email, ROOT_EMAIL):
        raise HTTPException(status_code=403, detail="Face login is root-only")

    # nonce: 一次性挑战码(challenge),存入 session 并返回给前端
    # 前端在登录时必须携带该 nonce,后端验证后立即销毁
    # 用于防止请求被截获后重复利用(Replay Attack)
    nonce_in_session = request.session.get("root_face_nonce", "")
    request.session.pop("root_face_nonce", None) # pop是字典方法,从session里取出root_face_nonce的值(如果没有就返回空字符串),然后删除这个键值对(防止重放攻击)
    if not nonce_in_session or not hmac.compare_digest(req.nonce, nonce_in_session):
        raise HTTPException(status_code=400, detail="Invalid nonce")

    user = db.query(User).filter(User.email == email).first()
    if not user or user.role != "root":
        raise HTTPException(status_code=403, detail="Root account not found")

    # 数据库中存的embedding_json是JSON字符串,类似于"[0.12, -0.33, 0.89, ...]"
    # 取出来之后row是元组,类似于row = ('[0.12, -0.33, ...]', 0.45)
    row = db.execute(
        text("SELECT embedding_json, threshold FROM user_face_credentials WHERE user_id = :uid"), 
        {"uid": user.id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Root face not enrolled")

    try:
        emb_live = face_engine.extract_normed_embedding(req.image_b64)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    emb_saved = json.loads(row[0])
    threshold = float(row[1] if row[1] is not None else 0.45)

    score = face_engine.cosine_similarity(emb_live, emb_saved)
    if score < threshold:
        raise HTTPException(status_code=401, detail=f"Face mismatch (score={score:.4f})")

    request.session["uid"] = user.id # 将当前登录用户的id写进session,后续请求就能通过这个id识别用户身份(调用require_user函数)
    return {"ok": True, "email": user.email, "role": user.role, "score": score}


@app.post("/api/root/face/enroll")
def root_face_enroll(req: RootFaceEnrollReq, root: User = Depends(require_root), db: Session = Depends(get_db)):
    try:
        emb = face_engine.extract_normed_embedding(req.image_b64)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    emb_json = json.dumps(emb) # 将Python列表对象转成JSON字符串,方便存进数据库

    exists = db.execute(
        text("SELECT id FROM user_face_credentials WHERE user_id = :uid"),
        {"uid": root.id},
    ).fetchone()

    if exists: # 存在就更新
        db.execute(
            text(
                "UPDATE user_face_credentials "
                "SET embedding_json = :emb, updated_at = CURRENT_TIMESTAMP " # CURRENT_TIMESTAMP是SQL内置函数,表示数据库自动记录更新时间
                "WHERE user_id = :uid"
            ),
            {"emb": emb_json, "uid": root.id},
        )
    else: # 不存在就插入
        db.execute(
            text(
                "INSERT INTO user_face_credentials(user_id, embedding_json, threshold) " # 插入这3列数据
                "VALUES(:uid, :emb, :th)" # 指定插入的值
            ),
            {"uid": root.id, "emb": emb_json, "th": 0.45},
        )

    db.commit() # 将上面的修改真正写入数据库,否则修改只存在内存里,程序结束就没了
    return {"ok": True}


# ------------------------- 前端资源和首页路由 -------------------------
# 1.用户访问 /
# 2.返回index.html
# 3.index.html引入js/css
# 4.浏览器请求/static/xxx
# 5.FastAPI从本地static目录读取文件
# 6.页面完整加载
#--------------------------------------------------------------------


# 把本地文件夹 webapp/static 挂载到网站的 /static 路径下,让浏览器可以直接访问里面的前端文件
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")


@app.get("/")
def home():
    return FileResponse("webapp/static/index.html")
