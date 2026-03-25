"""
定义数据库ORM模型类的子类User类,用于描述用户表结构
"""
# 导入定义表字段时要用的工具,Column定义数据库表中的一列,func调用SQLAlchemy提供的SQL函数接口
from sqlalchemy import Column, Integer, String, DateTime, func
from .db import Base

class User(Base): # Python的SQLAlchemy ORM模型类
    __tablename__ = "users" # 这句是在指定：这个模型类对应数据库里的哪张表

    id = Column(Integer, primary_key=True, index=True) # 设为主键并给这一列建索引
    email = Column(String(320), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    provider = Column(String(32), nullable=False, default="password")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

