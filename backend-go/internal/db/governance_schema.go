package db

import (
	"context"
	"database/sql"
)

func EnsureGovernanceSchema(ctx context.Context, db *sql.DB) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS organizations (
			id BIGINT NOT NULL AUTO_INCREMENT,
			owner_user_id BIGINT NOT NULL,
			name VARCHAR(120) NOT NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(id),
			INDEX idx_org_owner(owner_user_id),
			CONSTRAINT fk_org_owner FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS organization_members (
			organization_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,
			role VARCHAR(20) NOT NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(organization_id,user_id),
			INDEX idx_org_member_user(user_id),
			CONSTRAINT fk_org_member_org FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
			CONSTRAINT fk_org_member_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,

		`CREATE TABLE IF NOT EXISTS organization_projects (
			organization_id BIGINT NOT NULL,
			project_id BIGINT NOT NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id),
			INDEX idx_org_projects_org(organization_id),
			CONSTRAINT fk_org_project_org FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
			CONSTRAINT fk_org_project_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_members (
			project_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,
			role VARCHAR(20) NOT NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id,user_id),
			INDEX idx_project_member_user(user_id,project_id),
			CONSTRAINT fk_project_member_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
			CONSTRAINT fk_project_member_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_quotas (
			project_id BIGINT NOT NULL,
			requests_per_minute BIGINT NOT NULL DEFAULT 60,
			concurrent_tasks BIGINT NOT NULL DEFAULT 8,
			monthly_token_limit BIGINT NOT NULL DEFAULT 10000000,
			monthly_cost_limit DECIMAL(18,6) NOT NULL DEFAULT 100.000000,
			daily_tool_action_limit BIGINT NOT NULL DEFAULT 10000,
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id),
			CONSTRAINT fk_project_quota_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_usage_monthly (
			project_id BIGINT NOT NULL,
			month_key CHAR(7) NOT NULL,
			request_count BIGINT NOT NULL DEFAULT 0,
			token_count BIGINT NOT NULL DEFAULT 0,
			estimated_cost DECIMAL(18,6) NOT NULL DEFAULT 0,
			tool_action_count BIGINT NOT NULL DEFAULT 0,
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id,month_key),
			CONSTRAINT fk_project_usage_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,

		`CREATE TABLE IF NOT EXISTS project_request_windows (
			project_id BIGINT NOT NULL,
			minute_key CHAR(16) NOT NULL,
			request_count BIGINT NOT NULL DEFAULT 0,
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id,minute_key),
			CONSTRAINT fk_project_request_window_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_usage_daily (
			project_id BIGINT NOT NULL,
			day_key CHAR(10) NOT NULL,
			tool_action_count BIGINT NOT NULL DEFAULT 0,
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id,day_key),
			CONSTRAINT fk_project_usage_daily_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_secrets (
			id BIGINT NOT NULL AUTO_INCREMENT,
			project_id BIGINT NOT NULL,
			name VARCHAR(100) NOT NULL,
			kind VARCHAR(40) NOT NULL,
			ciphertext LONGBLOB NOT NULL,
			nonce VARBINARY(32) NOT NULL,
			masked_hint VARCHAR(64) NOT NULL,
			created_by BIGINT NOT NULL,
			last_used_at TIMESTAMP(6) NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(id),
			UNIQUE KEY uk_project_secret_name(project_id,name),
			CONSTRAINT fk_project_secret_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
			CONSTRAINT fk_project_secret_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE RESTRICT
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_model_providers (
			project_id BIGINT NOT NULL,
			provider VARCHAR(40) NOT NULL,
			base_url VARCHAR(512) NOT NULL,
			model_name VARCHAR(120) NOT NULL,
			secret_id BIGINT NULL,
			enabled TINYINT(1) NOT NULL DEFAULT 1,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
			PRIMARY KEY(project_id),
			CONSTRAINT fk_project_provider_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
			CONSTRAINT fk_project_provider_secret FOREIGN KEY(secret_id) REFERENCES project_secrets(id) ON DELETE SET NULL
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS audit_events (
			id BIGINT NOT NULL AUTO_INCREMENT,
			project_id BIGINT NULL,
			actor_user_id BIGINT NOT NULL,
			action VARCHAR(120) NOT NULL,
			resource_type VARCHAR(80) NOT NULL,
			resource_id VARCHAR(120) NOT NULL DEFAULT '',
			result VARCHAR(24) NOT NULL,
			metadata_json JSON NULL,
			created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
			PRIMARY KEY(id),
			INDEX idx_audit_project_created(project_id,created_at),
			INDEX idx_audit_actor_created(actor_user_id,created_at),
			CONSTRAINT fk_audit_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
			CONSTRAINT fk_audit_actor FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	}
	for _, stmt := range statements {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			return err
		}
	}
	return nil
}
