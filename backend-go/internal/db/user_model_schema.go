package db

import (
	"context"
	"database/sql"
)

// EnsureUserModelSchema keeps the legacy single-provider table intact for
// backward compatibility and adds the multi-service model pool used by the
// current product. Plaintext API keys never enter either table.
func EnsureUserModelSchema(ctx context.Context, db *sql.DB) error {
	if _, err := db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS user_model_providers (
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
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`); err != nil {
		return err
	}

	if _, err := db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS user_model_services (
		id BIGINT NOT NULL AUTO_INCREMENT,
		service_key CHAR(36) NOT NULL,
		user_id BIGINT NOT NULL,
		name VARCHAR(120) NOT NULL,
		provider VARCHAR(40) NOT NULL,
		base_url VARCHAR(512) NOT NULL,
		model_name VARCHAR(120) NOT NULL,
		vision_model_name VARCHAR(120) NOT NULL DEFAULT '',
		ciphertext LONGBLOB NOT NULL,
		nonce VARBINARY(32) NOT NULL,
		masked_hint VARCHAR(64) NOT NULL,
		enabled TINYINT(1) NOT NULL DEFAULT 1,
		auto_route TINYINT(1) NOT NULL DEFAULT 1,
		is_default TINYINT(1) NOT NULL DEFAULT 0,
		created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
		updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
		PRIMARY KEY(id),
		UNIQUE KEY uq_user_model_services_service_key(service_key),
		INDEX idx_user_model_services_user(user_id, enabled, auto_route),
		INDEX idx_user_model_services_default(user_id, is_default),
		CONSTRAINT fk_user_model_services_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`); err != nil {
		return err
	}

	// Persist only the browser-selected routing intent (auto/manual + service id),
	// never the API key. Resume and durable dispatch therefore keep the original
	// task-level override while credentials are re-resolved at execution time.
	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"model_selection_json",
		`ALTER TABLE tasks ADD COLUMN model_selection_json JSON NULL AFTER synthesis_mode`,
	); err != nil {
		return err
	}

	return nil
}
