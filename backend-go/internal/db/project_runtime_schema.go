package db

import (
	"context"
	"database/sql"
)

func EnsureProjectRuntimeSchema(
	ctx context.Context,
	db *sql.DB,
) error {
	statements := []string{
		`
		CREATE TABLE IF NOT EXISTS project_runtime_profiles (
			project_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,

			agent_mode VARCHAR(16) NOT NULL DEFAULT 'all',
			tool_mode VARCHAR(16) NOT NULL DEFAULT 'all',
			mcp_mode VARCHAR(16) NOT NULL DEFAULT 'all',

			policy_mode VARCHAR(16) NOT NULL DEFAULT 'inherit',
			scheduler VARCHAR(32) NOT NULL DEFAULT 'adaptive',
			planner VARCHAR(32) NOT NULL DEFAULT 'multi_objective',
			execution_mode VARCHAR(32) NOT NULL DEFAULT 'auto',
			synthesis_mode VARCHAR(32) NOT NULL DEFAULT 'auto',

			max_latency_ms BIGINT NOT NULL DEFAULT 8000,
			max_cost DOUBLE NOT NULL DEFAULT 0.15,
			min_quality DOUBLE NOT NULL DEFAULT 0.8,

			created_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6),

			updated_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),

			PRIMARY KEY (project_id),

			INDEX idx_project_runtime_user (
				user_id,
				updated_at
			),

			CONSTRAINT fk_project_runtime_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,

			CONSTRAINT fk_project_runtime_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS project_agent_bindings (
			project_id BIGINT NOT NULL,
			agent_id BIGINT NOT NULL,
			created_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6),

			PRIMARY KEY (project_id, agent_id),

			INDEX idx_project_agent_agent (agent_id),

			CONSTRAINT fk_project_agent_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,

			CONSTRAINT fk_project_agent_agent
				FOREIGN KEY (agent_id)
				REFERENCES agents(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS project_tool_bindings (
			project_id BIGINT NOT NULL,
			tool_id BIGINT NOT NULL,
			created_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6),

			PRIMARY KEY (project_id, tool_id),

			INDEX idx_project_tool_tool (tool_id),

			CONSTRAINT fk_project_tool_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,

			CONSTRAINT fk_project_tool_tool
				FOREIGN KEY (tool_id)
				REFERENCES tools(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS project_mcp_bindings (
			project_id BIGINT NOT NULL,
			mcp_server_id BIGINT NOT NULL,
			created_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6),

			PRIMARY KEY (project_id, mcp_server_id),

			INDEX idx_project_mcp_server (mcp_server_id),

			CONSTRAINT fk_project_mcp_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,

			CONSTRAINT fk_project_mcp_server
				FOREIGN KEY (mcp_server_id)
				REFERENCES mcp_servers(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
	}

	for _, statement := range statements {
		if _, err := db.ExecContext(
			ctx,
			statement,
		); err != nil {
			return err
		}
	}

	_, err := db.ExecContext(
		ctx,
		`
		INSERT INTO project_runtime_profiles(
			project_id,
			user_id
		)
		SELECT
			p.id,
			p.user_id
		FROM projects p
		ON DUPLICATE KEY UPDATE
			user_id = p.user_id
		`,
	)

	return err
}
