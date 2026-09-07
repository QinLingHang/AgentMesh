USE agentmesh_mvp;
CREATE TABLE IF NOT EXISTS mcp_servers (
  id BIGINT NOT NULL AUTO_INCREMENT, user_id BIGINT NOT NULL, name VARCHAR(100) NOT NULL,
  transport VARCHAR(32) NOT NULL DEFAULT 'streamable_http', endpoint VARCHAR(500) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1, connect_timeout_ms BIGINT NOT NULL DEFAULT 5000,
  call_timeout_ms BIGINT NOT NULL DEFAULT 10000, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY(id), UNIQUE KEY uk_mcp_server_user_name(user_id,name), KEY idx_mcp_server_user_enabled(user_id,enabled),
  CONSTRAINT fk_mcp_server_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
