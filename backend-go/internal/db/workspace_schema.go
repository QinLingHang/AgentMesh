package db

import (
	"context"
	"database/sql"
	"fmt"
)

// EnsureWorkspaceSchema upgrades existing AgentMesh databases in place.
//
// Development-stage policy:
//   - never drop the existing Docker volume;
//   - keep old Project Knowledge rows;
//   - evolve them into the KnowledgeBase model idempotently.
//
// A formal migration tool should replace this bootstrap before production.
func EnsureWorkspaceSchema(
	ctx context.Context,
	db *sql.DB,
) error {
	statements := []string{
		`
		CREATE TABLE IF NOT EXISTS projects (
			id BIGINT NOT NULL AUTO_INCREMENT,
			user_id BIGINT NOT NULL,
			name VARCHAR(80) NOT NULL,
			description VARCHAR(240) NOT NULL DEFAULT '',
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY (id),
			INDEX idx_projects_user_updated (user_id, updated_at),
			CONSTRAINT fk_projects_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS project_conversations (
			project_id BIGINT NOT NULL,
			conversation_id BIGINT NOT NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			PRIMARY KEY (conversation_id),
			INDEX idx_project_conversations_project (project_id, created_at),
			CONSTRAINT fk_project_conversations_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_project_conversations_conversation
				FOREIGN KEY (conversation_id)
				REFERENCES conversations(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS knowledge_bases (
			id BIGINT NOT NULL AUTO_INCREMENT,
			user_id BIGINT NOT NULL,
			identity_key VARCHAR(160) NOT NULL,
			name VARCHAR(80) NOT NULL,
			description VARCHAR(240) NOT NULL DEFAULT '',
			scope VARCHAR(16) NOT NULL,
			project_id BIGINT NULL,
			is_default TINYINT(1) NOT NULL DEFAULT 0,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY (id),
			UNIQUE KEY uk_knowledge_base_identity (user_id, identity_key),
			INDEX idx_knowledge_base_scope (user_id, scope, updated_at),
			INDEX idx_knowledge_base_project (user_id, project_id, updated_at),
			CONSTRAINT fk_knowledge_base_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_knowledge_base_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS project_knowledge_files (
			id BIGINT NOT NULL AUTO_INCREMENT,
			project_id BIGINT NULL,
			knowledge_base_id BIGINT NULL,
			user_id BIGINT NOT NULL,
			original_name VARCHAR(255) NOT NULL,
			media_type VARCHAR(128) NOT NULL,
			extension VARCHAR(16) NOT NULL,
			size_bytes BIGINT NOT NULL,
			checksum_sha256 CHAR(64) NOT NULL,
			storage_key VARCHAR(512) NOT NULL,
			status VARCHAR(32) NOT NULL DEFAULT 'UPLOADED',
			chunk_count INT NOT NULL DEFAULT 0,
			error_message VARCHAR(1000) NULL,
			indexed_at TIMESTAMP(6) NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY (id),
			UNIQUE KEY uk_project_knowledge_storage_key (storage_key),
			INDEX idx_project_knowledge_project_created (user_id, project_id, created_at),
			INDEX idx_project_knowledge_base_created (user_id, knowledge_base_id, created_at),
			INDEX idx_project_knowledge_status (user_id, status),
			CONSTRAINT fk_project_knowledge_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_project_knowledge_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_project_knowledge_base
				FOREIGN KEY (knowledge_base_id)
				REFERENCES knowledge_bases(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
		`
		CREATE TABLE IF NOT EXISTS project_global_knowledge_bindings (
			project_id BIGINT NOT NULL,
			knowledge_base_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			PRIMARY KEY (project_id, knowledge_base_id),
			INDEX idx_project_global_kb_user (user_id, project_id),
			CONSTRAINT fk_project_global_kb_project
				FOREIGN KEY (project_id)
				REFERENCES projects(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_project_global_kb_base
				FOREIGN KEY (knowledge_base_id)
				REFERENCES knowledge_bases(id)
				ON DELETE CASCADE,
			CONSTRAINT fk_project_global_kb_user
				FOREIGN KEY (user_id)
				REFERENCES users(id)
				ON DELETE CASCADE
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
	}

	for _, statement := range statements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return err
		}
	}

	if err := evolveKnowledgeFileTable(ctx, db); err != nil {
		return err
	}

	if err := seedKnowledgeBases(ctx, db); err != nil {
		return err
	}

	return nil
}

func columnExists(
	ctx context.Context,
	db *sql.DB,
	table string,
	column string,
) (bool, error) {
	var count int

	err := db.QueryRowContext(
		ctx,
		`
		SELECT COUNT(*)
		FROM information_schema.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = ?
		  AND COLUMN_NAME = ?
		`,
		table,
		column,
	).Scan(&count)

	return count > 0, err
}

func constraintExists(
	ctx context.Context,
	db *sql.DB,
	table string,
	constraint string,
) (bool, error) {
	var count int

	err := db.QueryRowContext(
		ctx,
		`
		SELECT COUNT(*)
		FROM information_schema.TABLE_CONSTRAINTS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = ?
		  AND CONSTRAINT_NAME = ?
		`,
		table,
		constraint,
	).Scan(&count)

	return count > 0, err
}

func indexExists(
	ctx context.Context,
	db *sql.DB,
	table string,
	index string,
) (bool, error) {
	var count int

	err := db.QueryRowContext(
		ctx,
		`
		SELECT COUNT(*)
		FROM information_schema.STATISTICS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = ?
		  AND INDEX_NAME = ?
		`,
		table,
		index,
	).Scan(&count)

	return count > 0, err
}

func evolveKnowledgeFileTable(
	ctx context.Context,
	db *sql.DB,
) error {
	exists, err := columnExists(
		ctx,
		db,
		"project_knowledge_files",
		"knowledge_base_id",
	)
	if err != nil {
		return err
	}

	if !exists {
		if _, err = db.ExecContext(
			ctx,
			`ALTER TABLE project_knowledge_files
			 ADD COLUMN knowledge_base_id BIGINT NULL AFTER project_id`,
		); err != nil {
			return err
		}
	}

	// Existing v2.3G-1 installations used NOT NULL project_id.
	// Global knowledge files need project_id = NULL.
	if _, err = db.ExecContext(
		ctx,
		`ALTER TABLE project_knowledge_files
		 MODIFY COLUMN project_id BIGINT NULL`,
	); err != nil {
		return err
	}

	indexOK, err := indexExists(
		ctx,
		db,
		"project_knowledge_files",
		"idx_project_knowledge_base_created",
	)
	if err != nil {
		return err
	}

	if !indexOK {
		if _, err = db.ExecContext(
			ctx,
			`ALTER TABLE project_knowledge_files
			 ADD INDEX idx_project_knowledge_base_created
			 (user_id, knowledge_base_id, created_at)`,
		); err != nil {
			return err
		}
	}

	constraintOK, err := constraintExists(
		ctx,
		db,
		"project_knowledge_files",
		"fk_project_knowledge_base",
	)
	if err != nil {
		return err
	}

	if !constraintOK {
		if _, err = db.ExecContext(
			ctx,
			`ALTER TABLE project_knowledge_files
			 ADD CONSTRAINT fk_project_knowledge_base
			 FOREIGN KEY (knowledge_base_id)
			 REFERENCES knowledge_bases(id)
			 ON DELETE CASCADE`,
		); err != nil {
			return err
		}
	}

	return nil
}

func seedKnowledgeBases(
	ctx context.Context,
	db *sql.DB,
) error {
	// Every user gets one default global knowledge base.
	if _, err := db.ExecContext(
		ctx,
		`
		INSERT INTO knowledge_bases(
			user_id,
			identity_key,
			name,
			description,
			scope,
			project_id,
			is_default
		)
		SELECT
			u.id,
			'global:default',
			'全局知识库',
			'普通会话默认可用的个人通用知识。',
			'GLOBAL',
			NULL,
			1
		FROM users u
		ON DUPLICATE KEY UPDATE
			is_default = 1
		`,
	); err != nil {
		return fmt.Errorf("seed global knowledge bases: %w", err)
	}

	// Every Project gets one default Project knowledge base.
	if _, err := db.ExecContext(
		ctx,
		`
		INSERT INTO knowledge_bases(
			user_id,
			identity_key,
			name,
			description,
			scope,
			project_id,
			is_default
		)
		SELECT
			p.user_id,
			CONCAT('project:', p.id, ':default'),
			CONCAT(p.name, ' · 项目知识'),
			'当前项目专属知识。',
			'PROJECT',
			p.id,
			1
		FROM projects p
		ON DUPLICATE KEY UPDATE
			is_default = 1
		`,
	); err != nil {
		return fmt.Errorf("seed project knowledge bases: %w", err)
	}

	// Migrate old v2.3G-1 Project Knowledge rows into their default Project KB.
	if _, err := db.ExecContext(
		ctx,
		`
		UPDATE project_knowledge_files f
		INNER JOIN knowledge_bases kb
			ON kb.user_id = f.user_id
		   AND kb.project_id = f.project_id
		   AND kb.scope = 'PROJECT'
		   AND kb.is_default = 1
		SET f.knowledge_base_id = kb.id
		WHERE f.knowledge_base_id IS NULL
		  AND f.project_id IS NOT NULL
		`,
	); err != nil {
		return fmt.Errorf("migrate project knowledge files: %w", err)
	}

	return nil
}
