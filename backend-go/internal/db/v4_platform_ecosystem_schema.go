package db

import (
	"context"
	"database/sql"
)

// EnsureV4PlatformEcosystemSchema adds the persistent platform-ecosystem
// primitives introduced by V4: project-scoped service accounts, idempotent
// public API requests, marketplace packages/versions/installations, and API
// usage counters. The migration is additive and idempotent.
func EnsureV4PlatformEcosystemSchema(ctx context.Context, db *sql.DB) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS api_service_accounts (
            id BIGINT NOT NULL AUTO_INCREMENT,
            project_id BIGINT NOT NULL,
            name VARCHAR(120) NOT NULL,
            key_prefix VARCHAR(40) NOT NULL,
            secret_hash CHAR(64) NOT NULL,
            scopes_json JSON NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
            created_by BIGINT NOT NULL,
            expires_at DATETIME(6) NULL,
            last_used_at DATETIME(6) NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY(id),
            UNIQUE KEY uk_api_service_account_prefix(key_prefix),
            KEY idx_api_service_account_project(project_id,status),
            CONSTRAINT fk_api_service_account_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            CONSTRAINT fk_api_service_account_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS api_idempotency_records (
            service_account_id BIGINT NOT NULL,
            idempotency_key VARCHAR(160) NOT NULL,
            request_hash CHAR(64) NOT NULL,
            response_json JSON NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'IN_PROGRESS',
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            PRIMARY KEY(service_account_id,idempotency_key),
            KEY idx_api_idempotency_created(created_at),
            CONSTRAINT fk_api_idempotency_service_account FOREIGN KEY(service_account_id) REFERENCES api_service_accounts(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS api_usage_daily (
            service_account_id BIGINT NOT NULL,
            project_id BIGINT NOT NULL,
            day_key CHAR(10) NOT NULL,
            request_count BIGINT NOT NULL DEFAULT 0,
            error_count BIGINT NOT NULL DEFAULT 0,
            latency_ms_total BIGINT NOT NULL DEFAULT 0,
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY(service_account_id,day_key),
            KEY idx_api_usage_project(project_id,day_key),
            CONSTRAINT fk_api_usage_service_account FOREIGN KEY(service_account_id) REFERENCES api_service_accounts(id) ON DELETE CASCADE,
            CONSTRAINT fk_api_usage_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS ecosystem_packages (
            id BIGINT NOT NULL AUTO_INCREMENT,
            owner_user_id BIGINT NOT NULL,
            slug VARCHAR(120) NOT NULL,
            name VARCHAR(120) NOT NULL,
            kind VARCHAR(24) NOT NULL,
            summary VARCHAR(500) NOT NULL DEFAULT '',
            description TEXT NOT NULL,
            visibility VARCHAR(24) NOT NULL DEFAULT 'PRIVATE',
            status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
            latest_version VARCHAR(64) NOT NULL DEFAULT '',
            install_count BIGINT NOT NULL DEFAULT 0,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY(id),
            UNIQUE KEY uk_ecosystem_package_slug(slug),
            KEY idx_ecosystem_marketplace(status,visibility,kind,updated_at),
            KEY idx_ecosystem_owner(owner_user_id,updated_at),
            CONSTRAINT fk_ecosystem_package_owner FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS ecosystem_package_versions (
            id BIGINT NOT NULL AUTO_INCREMENT,
            package_id BIGINT NOT NULL,
            version VARCHAR(64) NOT NULL,
            manifest_json JSON NOT NULL,
            checksum CHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'VALIDATED',
            created_by BIGINT NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            PRIMARY KEY(id),
            UNIQUE KEY uk_ecosystem_package_version(package_id,version),
            KEY idx_ecosystem_version_status(package_id,status,created_at),
            CONSTRAINT fk_ecosystem_version_package FOREIGN KEY(package_id) REFERENCES ecosystem_packages(id) ON DELETE CASCADE,
            CONSTRAINT fk_ecosystem_version_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS project_package_installations (
            id BIGINT NOT NULL AUTO_INCREMENT,
            project_id BIGINT NOT NULL,
            package_id BIGINT NOT NULL,
            version_id BIGINT NOT NULL,
            enabled TINYINT(1) NOT NULL DEFAULT 1,
            config_json JSON NOT NULL,
            resource_type VARCHAR(32) NOT NULL DEFAULT '',
            resource_id BIGINT NULL,
            installed_by BIGINT NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY(id),
            UNIQUE KEY uk_project_package(project_id,package_id),
            KEY idx_project_package_enabled(project_id,enabled),
            CONSTRAINT fk_project_package_project FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            CONSTRAINT fk_project_package_package FOREIGN KEY(package_id) REFERENCES ecosystem_packages(id) ON DELETE CASCADE,
            CONSTRAINT fk_project_package_version FOREIGN KEY(version_id) REFERENCES ecosystem_package_versions(id) ON DELETE RESTRICT,
            CONSTRAINT fk_project_package_installer FOREIGN KEY(installed_by) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	}

	for _, statement := range statements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return err
		}
	}
	return nil
}
