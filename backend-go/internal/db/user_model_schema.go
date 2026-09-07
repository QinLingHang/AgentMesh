package db

import (
	"context"
	"database/sql"
)

// EnsureUserModelSchema stores per-user BYOK credentials encrypted by the Go
// control plane. Plaintext API keys never enter this table.
func EnsureUserModelSchema(ctx context.Context, db *sql.DB) error {
	_, err := db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS user_model_providers (
		user_id BIGINT NOT NULL,
		provider VARCHAR(40) NOT NULL,
		base_url VARCHAR(512) NOT NULL,
		model_name VARCHAR(120) NOT NULL,
		vision_model_name VARCHAR(120) NOT NULL DEFAULT '',
		ciphertext LONGBLOB NOT NULL,
		nonce VARBINARY(32) NOT NULL,
		masked_hint VARCHAR(64) NOT NULL,
		enabled TINYINT(1) NOT NULL DEFAULT 1,
		created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
		updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
		PRIMARY KEY(user_id),
		CONSTRAINT fk_user_model_provider_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`)
	return err
}
