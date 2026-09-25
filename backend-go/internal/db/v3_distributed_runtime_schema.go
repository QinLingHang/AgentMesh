package db

import (
	"context"
	"database/sql"
)

// EnsureV3DistributedRuntimeSchema upgrades the durable runtime from the Durable Runtime
// single-node worker registry into a multi-node topology with an HA dispatcher
// lease and explicit cross-node fencing metadata. The migration is additive and
// idempotent so existing V2 volumes can be upgraded in place.
func EnsureV3DistributedRuntimeSchema(ctx context.Context, db *sql.DB) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS runtime_nodes (
            node_id VARCHAR(128) NOT NULL,
            zone VARCHAR(128) NOT NULL DEFAULT '',
            version VARCHAR(64) NOT NULL DEFAULT '',
            capacity INT NOT NULL DEFAULT 1,
            declared_capacity INT NOT NULL DEFAULT 1,
            active_executions INT NOT NULL DEFAULT 0,
            worker_count INT NOT NULL DEFAULT 1,
            draining TINYINT(1) NOT NULL DEFAULT 0,
            status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
            last_heartbeat_at DATETIME(6) NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY(node_id),
            KEY idx_runtime_node_health(last_heartbeat_at, draining, status),
            KEY idx_runtime_node_zone(zone, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
		`CREATE TABLE IF NOT EXISTS runtime_dispatcher_leases (
            lease_name VARCHAR(64) NOT NULL,
            holder_id VARCHAR(128) NOT NULL,
            epoch BIGINT NOT NULL DEFAULT 1,
            lease_until DATETIME(6) NOT NULL,
            last_heartbeat_at DATETIME(6) NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY(lease_name),
            KEY idx_runtime_dispatcher_lease(lease_until)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	}
	for _, statement := range statements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return err
		}
	}

	if err := ensureColumn(ctx, db, "runtime_nodes", "declared_capacity", `ALTER TABLE runtime_nodes ADD COLUMN declared_capacity INT NOT NULL DEFAULT 1 AFTER capacity`); err != nil {
		return err
	}

	workerColumns := []struct {
		name string
		ddl  string
	}{
		{"node_id", `ALTER TABLE runtime_workers ADD COLUMN node_id VARCHAR(128) NOT NULL DEFAULT '' AFTER worker_id`},
		{"zone", `ALTER TABLE runtime_workers ADD COLUMN zone VARCHAR(128) NOT NULL DEFAULT '' AFTER node_id`},
		{"version", `ALTER TABLE runtime_workers ADD COLUMN version VARCHAR(64) NOT NULL DEFAULT '' AFTER zone`},
		{"started_at", `ALTER TABLE runtime_workers ADD COLUMN started_at DATETIME(6) NULL AFTER version`},
		{"last_assignment_at", `ALTER TABLE runtime_workers ADD COLUMN last_assignment_at DATETIME(6) NULL AFTER active_executions`},
	}
	for _, column := range workerColumns {
		if err := ensureColumn(ctx, db, "runtime_workers", column.name, column.ddl); err != nil {
			return err
		}
	}

	jobColumns := []struct {
		name string
		ddl  string
	}{
		{"node_id", `ALTER TABLE runtime_jobs ADD COLUMN node_id VARCHAR(128) NULL AFTER worker_id`},
		{"fence_epoch", `ALTER TABLE runtime_jobs ADD COLUMN fence_epoch BIGINT NOT NULL DEFAULT 0 AFTER lease_token`},
		{"failover_retry_safe", `ALTER TABLE runtime_jobs ADD COLUMN failover_retry_safe TINYINT(1) NOT NULL DEFAULT 0 AFTER max_attempts`},
	}
	for _, column := range jobColumns {
		if err := ensureColumn(ctx, db, "runtime_jobs", column.name, column.ddl); err != nil {
			return err
		}
	}

	// Existing legacy workers become one-node-per-worker until their next V3
	// heartbeat supplies an explicit node identity. This preserves scheduling
	// availability during rolling upgrades.
	if _, err := db.ExecContext(ctx, `
        UPDATE runtime_workers
        SET node_id = worker_id
        WHERE node_id = '' OR node_id IS NULL
    `); err != nil {
		return err
	}

	return nil
}
