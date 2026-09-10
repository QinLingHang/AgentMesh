package db

import (
	"context"
	"database/sql"
)

// EnsureConversationMemorySchema creates durable conversation-level memory
// capsules. The raw messages table remains authoritative; this table stores
// only bounded LLM-compressed projections that can be rebuilt from raw history.
func EnsureConversationMemorySchema(ctx context.Context, database *sql.DB) error {
	_, err := database.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS conversation_memory_capsules (
			id BIGINT NOT NULL AUTO_INCREMENT,
			user_id BIGINT NOT NULL,
			conversation_id BIGINT NOT NULL,
			start_message_id BIGINT NOT NULL,
			end_message_id BIGINT NOT NULL,
			summary TEXT NOT NULL,
			facts_json JSON NOT NULL,
			decisions_json JSON NOT NULL,
			open_tasks_json JSON NOT NULL,
			entities_json JSON NOT NULL,
			keywords_json JSON NOT NULL,
			importance DECIMAL(6,5) NOT NULL DEFAULT 0.50000,
			source_hash CHAR(64) NOT NULL,
			compaction_model VARCHAR(160) NOT NULL DEFAULT '',
			input_tokens INT NOT NULL DEFAULT 0,
			output_tokens INT NOT NULL DEFAULT 0,
			estimated_cost DECIMAL(18,8) NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY (id),
			UNIQUE KEY uk_conversation_memory_range (
				conversation_id,
				start_message_id,
				end_message_id
			),
			INDEX idx_conversation_memory_lookup (
				user_id,
				conversation_id,
				end_message_id
			),
			CONSTRAINT fk_conversation_memory_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_conversation_memory_conversation
				FOREIGN KEY (conversation_id)
				REFERENCES conversations(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
	`)
	return err
}
