package db

import (
	"context"
	"database/sql"
)

// EnsureEventPlaneSchema owns the P21 Kafka consumer idempotency ledger.
// Kafka delivery is at-least-once; the ledger makes business effects idempotent
// across duplicate delivery, consumer restarts, and offset replay.
func EnsureEventPlaneSchema(ctx context.Context, db *sql.DB) error {
	_, err := db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS processed_runtime_events (
			event_id VARCHAR(64) NOT NULL,
			event_type VARCHAR(128) NOT NULL,
			event_version INT NOT NULL,
			execution_id VARCHAR(64) NULL,
			topic_name VARCHAR(255) NOT NULL,
			partition_id INT NOT NULL,
			offset_value BIGINT NOT NULL,
			processed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			PRIMARY KEY(event_id),
			UNIQUE KEY uk_runtime_event_position(topic_name, partition_id, offset_value),
			KEY idx_runtime_event_execution(execution_id, processed_at),
			KEY idx_runtime_event_processed(processed_at)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
	`)
	return err
}
