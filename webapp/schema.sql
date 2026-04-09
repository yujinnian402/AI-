-- webapp/schema.sql
-- 目标：邮箱注册用户表（支持以后 OAuth 扩展）
-- SQLite / Postgres 都能用（少量类型差异已规避）

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  email         VARCHAR(320) NOT NULL UNIQUE,
  password_hash VARCHAR(255),
  provider      VARCHAR(32) NOT NULL DEFAULT 'password',
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  role          VARCHAR(16) NOT NULL DEFAULT 'user'
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS user_face_credentials (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL UNIQUE,
  embedding_json TEXT NOT NULL,
  model_name    VARCHAR(64) NOT NULL DEFAULT 'insightface-buffalo_l',
  threshold     FLOAT NOT NULL DEFAULT 0.45,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_face_credentials_user_id ON user_face_credentials(user_id);
