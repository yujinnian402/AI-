-- webapp/schema.sql
-- 目标：邮箱注册用户表（支持以后 OAuth 扩展）
-- SQLite / Postgres 都能用（少量类型差异已规避）

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  email         VARCHAR(320) NOT NULL UNIQUE,
  password_hash VARCHAR(255),          -- 只有邮箱密码登录才有；OAuth 用户可为空
  provider      VARCHAR(32) NOT NULL DEFAULT 'password',  -- 'password'/'github'/'google'/'apple'
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
