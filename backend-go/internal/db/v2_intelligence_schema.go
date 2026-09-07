package db

import (
	"context"
	"database/sql"
)

func EnsureV2IntelligenceSchema(ctx context.Context, db *sql.DB) error {
	_, err := db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS run_cost_records (
			task_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,
			project_id BIGINT NULL,
			provider VARCHAR(64) NOT NULL DEFAULT '',
			model_name VARCHAR(191) NOT NULL DEFAULT '',
			input_tokens BIGINT NOT NULL DEFAULT 0,
			output_tokens BIGINT NOT NULL DEFAULT 0,
			total_tokens BIGINT NOT NULL DEFAULT 0,
			estimated_cost DECIMAL(18,8) NOT NULL DEFAULT 0,
			cost_status VARCHAR(32) NOT NULL DEFAULT 'unavailable',
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY (task_id),
			INDEX idx_run_cost_user_created (user_id, created_at),
			INDEX idx_run_cost_project_created (project_id, created_at),
			INDEX idx_run_cost_model_created (provider, model_name, created_at),
			CONSTRAINT fk_run_cost_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
			CONSTRAINT fk_run_cost_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
	`)
	return err
}
