package db

import (
	"context"
	"database/sql"
)

func EnsureAttachmentSchema(ctx context.Context, database *sql.DB) error {
	_, err := database.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS conversation_attachments (
			id BIGINT NOT NULL AUTO_INCREMENT,
			user_id BIGINT NOT NULL,
			conversation_id BIGINT NOT NULL,
			original_name VARCHAR(255) NOT NULL,
			media_type VARCHAR(128) NOT NULL,
			extension VARCHAR(32) NOT NULL,
			size_bytes BIGINT NOT NULL,
			checksum_sha256 CHAR(64) NOT NULL,
			storage_key VARCHAR(512) NOT NULL,
			created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
			PRIMARY KEY (id),
			KEY idx_conversation_attachments_user_conversation (user_id, conversation_id, id),
			CONSTRAINT fk_conversation_attachments_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
			CONSTRAINT fk_conversation_attachments_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
	`)
	return err
}
