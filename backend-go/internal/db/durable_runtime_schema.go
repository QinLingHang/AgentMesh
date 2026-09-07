package db

import (
	"context"
	"database/sql"
)

// EnsureDurableRuntimeSchema adds the P8 durable execution control-plane
// tables. It is additive and safe for existing Docker volumes.
func EnsureDurableRuntimeSchema(ctx context.Context, db *sql.DB) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS runtime_workers (
			worker_id VARCHAR(128) NOT NULL,
			endpoint VARCHAR(500) NOT NULL,
			capacity INT NOT NULL DEFAULT 1,
			active_executions INT NOT NULL DEFAULT 0,
			draining TINYINT(1) NOT NULL DEFAULT 0,
			status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
			consecutive_failures INT NOT NULL DEFAULT 0,
			circuit_open_until DATETIME(6) NULL,
			last_heartbeat_at DATETIME(6) NOT NULL,
			created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(worker_id),
			KEY idx_runtime_worker_health(last_heartbeat_at, draining, status),
			KEY idx_runtime_worker_circuit(circuit_open_until)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS runtime_jobs (
			id BIGINT NOT NULL AUTO_INCREMENT,
			task_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,
			request_id VARCHAR(64) NOT NULL,
			execution_id VARCHAR(64) NOT NULL,
			request_json JSON NOT NULL,
			status VARCHAR(24) NOT NULL DEFAULT 'QUEUED',
			worker_id VARCHAR(128) NULL,
			lease_token VARCHAR(64) NULL,
			lease_expires_at DATETIME(6) NULL,
			accepted_at DATETIME(6) NULL,
			attempt_count INT NOT NULL DEFAULT 0,
			max_attempts INT NOT NULL DEFAULT 3,
			deadline_at DATETIME(6) NOT NULL,
			next_attempt_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			last_error VARCHAR(255) NULL,
			created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(id),
			UNIQUE KEY uk_runtime_job_task(task_id),
			UNIQUE KEY uk_runtime_job_execution(execution_id),
			KEY idx_runtime_job_dispatch(status, next_attempt_at, id),
			KEY idx_runtime_job_lease(status, lease_expires_at),
			KEY idx_runtime_job_deadline(status, deadline_at),
			CONSTRAINT fk_runtime_job_task FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
			CONSTRAINT fk_runtime_job_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	}

	for _, statement := range statements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return err
		}
	}

	if err := ensureColumn(ctx, db, "tasks", "delivery_mode", `
		ALTER TABLE tasks
		ADD COLUMN delivery_mode VARCHAR(24) NOT NULL DEFAULT 'direct' AFTER synthesis_mode
	`); err != nil {
		return err
	}

	return nil
}
