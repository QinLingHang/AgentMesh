CREATE DATABASE IF NOT EXISTS agentmesh_mvp CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE agentmesh_mvp;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT NOT NULL AUTO_INCREMENT,
  email VARCHAR(191) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_email (email)
);

CREATE TABLE IF NOT EXISTS user_memories (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  category VARCHAR(32) NOT NULL,
  memory_key VARCHAR(128) NOT NULL,
  content TEXT NOT NULL,
  source_type VARCHAR(32) NOT NULL DEFAULT 'explicit_user',
  confidence DOUBLE NOT NULL DEFAULT 1,
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  last_accessed_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_memory_key (user_id, memory_key),
  KEY idx_user_memory_status_updated (user_id, status, updated_at, id),
  KEY idx_user_memory_category_updated (user_id, category, updated_at, id),
  CONSTRAINT fk_user_memory_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  token_hash CHAR(64) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  revoked_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_refresh_hash (token_hash),
  KEY idx_refresh_user (user_id),
  CONSTRAINT fk_refresh_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversations (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  title VARCHAR(255) NOT NULL DEFAULT '新对话',
  last_message_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_conv_user_updated (user_id, updated_at, id),
  CONSTRAINT fk_conv_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
  id BIGINT NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  role VARCHAR(16) NOT NULL,
  content LONGTEXT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'COMPLETED',
  request_id VARCHAR(64) NULL,
  metadata_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_msg_conv_id (conversation_id, id),
  KEY idx_msg_request (request_id),
  CONSTRAINT fk_msg_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agents (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  name VARCHAR(100) NOT NULL,
  description VARCHAR(500) NOT NULL DEFAULT '',
  endpoint VARCHAR(500) NOT NULL,
  protocol VARCHAR(32) NOT NULL DEFAULT 'http',
  capabilities_json JSON NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'internal',
  model_name VARCHAR(128) NOT NULL DEFAULT '',
  quality_score DECIMAL(8,6) NOT NULL DEFAULT 0.800000,
  avg_latency_ms BIGINT NOT NULL DEFAULT 1000,
  avg_cost DECIMAL(12,6) NOT NULL DEFAULT 0,
  success_rate DECIMAL(8,6) NOT NULL DEFAULT 1.000000,
  failure_rate DECIMAL(8,6) NOT NULL DEFAULT 0.000000,
  current_load DECIMAL(8,6) NOT NULL DEFAULT 0.000000,
  status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_agent_user_status (user_id, status),
  CONSTRAINT fk_agent_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_runtime_metrics (
  id BIGINT NOT NULL AUTO_INCREMENT,
  agent_id BIGINT NOT NULL,
  task_request_id VARCHAR(64) NOT NULL,
  capability VARCHAR(64) NOT NULL,
  success TINYINT(1) NOT NULL,
  latency_ms BIGINT NOT NULL,
  cost DECIMAL(12,6) NOT NULL DEFAULT 0,
  error_type VARCHAR(64) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_metric_agent_created (agent_id, created_at),
  KEY idx_metric_request (task_request_id),
  CONSTRAINT fk_metric_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  conversation_id BIGINT NULL,
  request_id VARCHAR(64) NOT NULL,
  task_text LONGTEXT NOT NULL,
  scheduler VARCHAR(32) NOT NULL,
  constraints_json JSON NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  result_text LONGTEXT NULL,
  selected_agents_json JSON NULL,
  trace_json JSON NULL,
  dag_json JSON NULL,
  latency_ms BIGINT NULL,
  estimated_cost DECIMAL(12,6) NULL,
  error_message TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_task_request (request_id),
  KEY idx_task_user_created (user_id, created_at),
  CONSTRAINT fk_task_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_task_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tools (
  id BIGINT NOT NULL AUTO_INCREMENT, user_id BIGINT NOT NULL, name VARCHAR(100) NOT NULL,
  description VARCHAR(500) NOT NULL DEFAULT '', protocol VARCHAR(32) NOT NULL DEFAULT 'internal', endpoint VARCHAR(500) NOT NULL DEFAULT '',
  input_schema JSON NOT NULL, risk_level VARCHAR(16) NOT NULL DEFAULT 'low', requires_confirmation TINYINT(1) NOT NULL DEFAULT 0,
  enabled TINYINT(1) NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), UNIQUE KEY uk_tool_user_name (user_id,name), KEY idx_tool_user_enabled (user_id,enabled),
  CONSTRAINT fk_tool_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mcp_servers (
  id BIGINT NOT NULL AUTO_INCREMENT, user_id BIGINT NOT NULL, name VARCHAR(100) NOT NULL,
  transport VARCHAR(32) NOT NULL DEFAULT 'streamable_http', endpoint VARCHAR(500) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1, connect_timeout_ms BIGINT NOT NULL DEFAULT 5000,
  call_timeout_ms BIGINT NOT NULL DEFAULT 10000, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY(id), UNIQUE KEY uk_mcp_server_user_name(user_id,name), KEY idx_mcp_server_user_enabled(user_id,enabled),
  CONSTRAINT fk_mcp_server_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
