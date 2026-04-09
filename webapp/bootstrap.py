from sqlalchemy import text # 把原始SQL字符串包装成SQLAlchemy可以执行的对象
from sqlalchemy.orm import Session # session是SQLAlchemy的数据库会话类型,是Python程序和数据库之间的一次"工作会话"
from passlib.context import CryptContext
from webapp.models import User


def run_lightweight_migrations(engine): # engine是db.py中创建的数据库引擎对象
    """
    执行轻量级数据库结构迁移(schema migration)

    功能：
        在应用启动时检查数据库当前表结构,
        自动补齐缺失字段或表,保证数据库结构与代码一致。

    使用场景：
        - 项目升级后新增字段(如 users.role)
        - 旧数据库仍然在使用,需要向前兼容
        - 不使用 Alembic 等正式迁移工具时的简化方案

    参数：
        engine (SQLAlchemy Engine):
            数据库连接引擎,用于执行底层SQL操作

    返回：
        None

    副作用：
        - 可能执行 ALTER TABLE 修改已有表结构
        - 可能创建新表(如 user_face_credentials)
        - 可能创建索引

    核心实现：
        1. 使用 PRAGMA table_info 查询表结构
        2. 解析已有字段列表
        3. 若缺失字段,则动态执行 ALTER TABLE 补齐
        4. 使用 CREATE TABLE IF NOT EXISTS 保证表存在
        5. 使用 CREATE INDEX IF NOT EXISTS 创建索引

    注意：
        - 属于“轻量迁移”,不具备版本管理能力
        - 不适合复杂 schema 演进(推荐 Alembic)
    """
    # 从数据库引擎engine开启一个事务性连接,将这个连接对象命名为conn
    # with...as...是Python的上下文管理器写法
    with engine.begin() as conn:
        # fetchall()将所有结果行一次性取出来(以Python列表的形式),每行是一个元组,得到的是表结构信息而不是表数据!
        cols = conn.execute(text("PRAGMA table_info(users)")).fetchall() # 此处SQL的写法查看表users结构
        # 把每一列的列名取出来组成一个集合,方便后面判断某列是否存在(集合的查找效率比列表更高)
        col_names = {c[1] for c in cols} # 集合推导式
        if "role" not in col_names:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'user'")
            )

        # root 人脸特征表
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS user_face_credentials (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE,
                    embedding_json TEXT NOT NULL,
                    model_name VARCHAR(64) NOT NULL DEFAULT 'insightface-buffalo_l',
                    threshold FLOAT NOT NULL DEFAULT 0.45,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_user_face_credentials_user_id " # 命名规则:idx_表名_字段名
                "ON user_face_credentials(user_id)" # 给user_id字段建立索引
            )
        )


def ensure_root_user(
    db: Session,
    pwd: CryptContext,
    root_email: str,
    root_password: str,
):
    """
    确保系统存在 root 管理员账号(初始化/修复)

    功能：
        检查数据库中是否存在指定邮箱的用户,
        若不存在则创建 root 用户；
        若存在但角色或密码不符合要求,则进行修复。

    使用场景：
        - 系统首次启动时创建管理员账号
        - 数据库被清空或损坏后的恢复
        - 保证系统始终存在可用的 root 权限入口

    参数：
        db (Session):
            SQLAlchemy数据库会话对象

        pwd (CryptContext):
            密码哈希工具,用于加密明文密码

        root_email (str):
            root用户邮箱(通常来自环境变量)

        root_password (str):
            root用户初始密码(明文,会被加密存储)

    返回：
        None

    副作用：
        - 可能向 users 表插入新用户
        - 可能修改已有用户的 role 或 password_hash

    核心逻辑：
        1. 标准化邮箱(strip + lower)
        2. 查询数据库是否存在该用户
        3. 若不存在 → 创建 root 用户
        4. 若存在：
            - 强制 role = "root"
            - 若无密码则补充密码
        5. 提交事务

    安全注意：
        - root_password 应来自安全环境变量(避免硬编码)
        - 不应在日志中打印明文密码
    
    
    """
    if not root_email or not root_password:
        return

    email = root_email.strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if u is None:
        u = User(
            email=email,
            password_hash=pwd.hash(root_password),
            provider="password",
            role="root",
        )
        db.add(u)
        db.commit()
        db.refresh(u) # 上一步commit提交之后再从数据库里把这条对象最新状态刷新回Python对象
        return # 创建完root之后直接结束函数

    changed = False # 标记变量,目前还没改东西
    if u.role != "root":
        u.role = "root"
        changed = True
    if not u.password_hash:
        u.password_hash = pwd.hash(root_password)
        u.provider = "password"
        changed = True
    if changed:
        db.add(u)
        db.commit()