package db

import (
	"context"
	"database/sql"
)

// EnsureMemorySchema upgrades both existing and fresh AgentMesh databases with
// the user-global long-term-memory store.
//
// The absence of project_id is intentional: Memory is User-global while
// Project Knowledge remains strictly Project-scoped.
func EnsureMemorySchema(
	ctx context.Context,
	db *sql.DB,
) error {
	_, err := db.ExecContext(
		ctx,
		`
		CREATE TABLE IF NOT EXISTS user_memories (
			id BIGINT NOT NULL AUTO_INCREMENT,
			user_id BIGINT NOT NULL,

			category VARCHAR(32) NOT NULL,
			memory_key VARCHAR(128) NOT NULL,
			content TEXT NOT NULL,

			source_type VARCHAR(32)
				NOT NULL
				DEFAULT 'explicit_user',

			confidence DOUBLE
				NOT NULL
				DEFAULT 1,

			status VARCHAR(16)
				NOT NULL
				DEFAULT 'active',

			last_accessed_at DATETIME(6) NULL,

			created_at DATETIME(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6),

			updated_at DATETIME(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),

			PRIMARY KEY (id),

			UNIQUE KEY uk_user_memory_key (
				user_id,
				memory_key
			),

			KEY idx_user_memory_status_updated (
				user_id,
				status,
				updated_at,
				id
			),

			KEY idx_user_memory_category_updated (
				user_id,
				category,
				updated_at,
				id
			),

			CONSTRAINT fk_user_memory_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
	)

	return err
}
