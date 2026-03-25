"""
负责数据库基础设施
包括配置数据库,创建数据库引擎,准备会话工厂,提供ORM基类,并且给FastAPI接口按请求分发数据库会话
"""
import os
from sqlalchemy import create_engine # 导入SQLAlchemy的创建数据库引擎函数
from sqlalchemy.orm import sessionmaker, declarative_base # 导入2个重要的ORM工具,分别用于创建会话工厂和创建ORM模型的父类

# 默认用你项目根目录的 app.db（你现在就是这个）
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db") # ///是SQLite的URL写法

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False} # 常见配置,防止出线程问题

# 创建引擎engine(python程序访问数据库的入口),参数pool_pre_ping=True是为了自动检测和回收失效的数据库连接,提高稳定性,每次从连接池中拿连接的时候先探测一下连接是否还活着
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) # 创建会话工厂
Base = declarative_base() # 创建Base父类,所有ORM模型都要继承这个Base

def get_db():
    """
    该函数进行数据库会话生命周期管理
    为每个请求创建分配一个数据库会话连接,提供给接口使用,请求结束自动关闭
    """
    db = SessionLocal() # 从会话工厂里面拿一个具体的数据库会话对象
    try:
        yield db # 把db提供给依赖它的路由函数使用
    finally:
        db.close()
