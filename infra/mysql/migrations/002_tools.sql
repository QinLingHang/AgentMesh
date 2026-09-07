USE agentmesh_mvp;
CREATE TABLE IF NOT EXISTS tools (
  id BIGINT NOT NULL AUTO_INCREMENT, user_id BIGINT NOT NULL, name VARCHAR(100) NOT NULL,
  description VARCHAR(500) NOT NULL DEFAULT '', protocol VARCHAR(32) NOT NULL DEFAULT 'internal', endpoint VARCHAR(500) NOT NULL DEFAULT '',
  input_schema JSON NOT NULL, risk_level VARCHAR(16) NOT NULL DEFAULT 'low', requires_confirmation TINYINT(1) NOT NULL DEFAULT 0,
  enabled TINYINT(1) NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), UNIQUE KEY uk_tool_user_name (user_id,name), KEY idx_tool_user_enabled (user_id,enabled),
  CONSTRAINT fk_tool_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
