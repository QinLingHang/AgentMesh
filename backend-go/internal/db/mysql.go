package db

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/config"

	_ "github.com/go-sql-driver/mysql"
)

// =========================================================
// Open MySQL
//
// Connection establishment is intentionally separate from schema migration.
// Production runs cmd/migrate before starting the control plane, while local
// server startup invokes db.Migrate as an idempotent safety net.
// =========================================================

func Open(
	cfg config.MySQL,
) (*sql.DB, error) {
	dsn := fmt.Sprintf(
		"%s:%s@tcp(%s:%v)/%s?charset=utf8mb4&parseTime=true&loc=UTC",
		cfg.User,
		cfg.Password,
		cfg.Host,
		cfg.Port,
		cfg.Database,
	)

	db, err := sql.Open(
		"mysql",
		dsn,
	)

	if err != nil {
		return nil, err
	}

	// =====================================================
	// Connection Pool
	//
	// sql.DB 不是一条数据库连接，
	// 而是 Go 内置的数据库连接池。
	// =====================================================

	db.SetMaxOpenConns(
		20,
	)

	db.SetMaxIdleConns(
		10,
	)

	db.SetConnMaxLifetime(
		30 * time.Minute,
	)

	db.SetConnMaxIdleTime(
		5 * time.Minute,
	)

	ctx, cancel := context.WithTimeout(
		context.Background(),
		10*time.Second,
	)

	defer cancel()

	if err = db.PingContext(
		ctx,
	); err != nil {
		_ = db.Close()

		return nil, fmt.Errorf(
			"mysql ping failed: %w",
			err,
		)
	}

	return db, nil
}

// =========================================================
// Runtime Incremental Schema
//
// 当前负责：
//
// v1.3
// agent_capability_profiles
//
// v1.9.5B
// Task Long-lived Runtime Lifecycle:
//
// planner
// execution_mode
// synthesis_mode
// continuation_json
// status VARCHAR(32)
// =========================================================

func ensureRuntimeSchema(
	ctx context.Context,
	db *sql.DB,
) error {
	// =====================================================
	// 1. Agent Capability Profile
	// =====================================================

	if _, err := db.ExecContext(
		ctx,
		`
		CREATE TABLE IF NOT EXISTS agent_capability_profiles (
			agent_id BIGINT NOT NULL,

			capability VARCHAR(128) NOT NULL,

			quality_score DOUBLE
				NOT NULL
				DEFAULT 0.8,

			avg_latency_ms BIGINT
				NOT NULL
				DEFAULT 1000,

			avg_cost DOUBLE
				NOT NULL
				DEFAULT 0,

			success_rate DOUBLE
				NOT NULL
				DEFAULT 1,

			failure_rate DOUBLE
				NOT NULL
				DEFAULT 0,

			sample_count BIGINT
				NOT NULL
				DEFAULT 0,

			created_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6),

			updated_at TIMESTAMP(6)
				NOT NULL
				DEFAULT CURRENT_TIMESTAMP(6)
				ON UPDATE CURRENT_TIMESTAMP(6),

			PRIMARY KEY (
				agent_id,
				capability
			),

			CONSTRAINT fk_agent_capability_profile_agent
				FOREIGN KEY (
					agent_id
				)
				REFERENCES agents(
					id
				)
				ON DELETE CASCADE,

			INDEX idx_agent_capability_profile_capability (
				capability
			),

			INDEX idx_agent_capability_profile_quality (
				quality_score
			),

			INDEX idx_agent_capability_profile_success (
				success_rate
			)
		)
		ENGINE=InnoDB
		DEFAULT CHARSET=utf8mb4
		COLLATE=utf8mb4_unicode_ci
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 2. Persist Planner
	// =====================================================

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"planner",
		`
		ALTER TABLE tasks
		ADD COLUMN planner
			VARCHAR(32)
			NOT NULL
			DEFAULT 'heuristic'
			AFTER scheduler
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 3. Persist Execution Mode
	// =====================================================

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"execution_mode",
		`
		ALTER TABLE tasks
		ADD COLUMN execution_mode
			VARCHAR(32)
			NOT NULL
			DEFAULT 'auto'
			AFTER planner
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 4. Persist Synthesis Mode
	// =====================================================

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"synthesis_mode",
		`
		ALTER TABLE tasks
		ADD COLUMN synthesis_mode
			VARCHAR(32)
			NOT NULL
			DEFAULT 'auto'
			AFTER execution_mode
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 4.1 Task-level model selection snapshot
	// =====================================================

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"model_selection_json",
		`
		ALTER TABLE tasks
		ADD COLUMN model_selection_json
			JSON NULL
			AFTER synthesis_mode
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 4.2 RAG policy snapshots
	//
	// rag_policy_json records the user/request intent.
	// effective_rag_policy_json records the authorized upper bound resolved
	// when the task was created. Runtime access still revalidates live auth.
	// =====================================================

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"rag_policy_json",
		`
		ALTER TABLE tasks
		ADD COLUMN rag_policy_json
			JSON NULL
			AFTER model_selection_json
		`,
	); err != nil {
		return err
	}

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"effective_rag_policy_json",
		`
		ALTER TABLE tasks
		ADD COLUMN effective_rag_policy_json
			JSON NULL
			AFTER rag_policy_json
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 5. Runtime Continuation
	//
	// 只存在于：
	//
	// INPUT_REQUIRED
	// AUTH_REQUIRED
	//
	// Resume 完成或任务失败后清空。
	// =====================================================

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"continuation_json",
		`
		ALTER TABLE tasks
		ADD COLUMN continuation_json
			JSON NULL
			AFTER error_message
		`,
	); err != nil {
		return err
	}

	// =====================================================
	// 6. Task Status Type
	//
	// 老 Schema 可能使用 ENUM：
	//
	// RUNNING
	// COMPLETED
	// ERROR
	//
	// 现在 Runtime 生命周期需要：
	//
	// RUNNING
	// INPUT_REQUIRED
	// AUTH_REQUIRED
	// COMPLETED
	// ERROR
	// CANCELED
	//
	// 所以统一升级为 VARCHAR(32)。
	// =====================================================

	if err := ensureTaskStatusColumn(
		ctx,
		db,
	); err != nil {
		return err
	}

	// P8 durable Runtime schema belongs to the normal incremental migration
	// path. This keeps production, integration tests and alternate entrypoints
	// on the same task schema instead of relying on cmd/server to add columns.
	if err := EnsureDurableRuntimeSchema(ctx, db); err != nil {
		return err
	}

	return nil
}

// =========================================================
// Ensure Column
//
// information_schema
//        ↓
// column exists?
//
// yes
// ↓
// skip
//
// no
// ↓
// ALTER TABLE ADD COLUMN
//
// 这样已有 Docker MySQL Volume 可以平滑升级。
// =========================================================

func ensureColumn(
	ctx context.Context,
	db *sql.DB,
	table string,
	column string,
	ddl string,
) error {
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
	).Scan(
		&count,
	)

	if err != nil {
		return err
	}

	if count > 0 {
		return nil
	}

	if _, err = db.ExecContext(
		ctx,
		ddl,
	); err != nil {
		return fmt.Errorf(
			"add column %s.%s failed: %w",
			table,
			column,
			err,
		)
	}

	return nil
}

// =========================================================
// Ensure Task Status Column
//
// 避免每次 Go 启动都执行：
//
// ALTER TABLE tasks MODIFY COLUMN status ...
//
// 只有发现当前数据库还是：
//
// ENUM
//
// 或者 VARCHAR 长度不足时才升级。
// =========================================================

func ensureTaskStatusColumn(
	ctx context.Context,
	db *sql.DB,
) error {
	var dataType string

	var columnType string

	var maxLength sql.NullInt64

	err := db.QueryRowContext(
		ctx,
		`
		SELECT
			DATA_TYPE,
			COLUMN_TYPE,
			CHARACTER_MAXIMUM_LENGTH
		FROM information_schema.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = 'tasks'
		  AND COLUMN_NAME = 'status'
		LIMIT 1
		`,
	).Scan(
		&dataType,
		&columnType,
		&maxLength,
	)

	if errorsIsNoRows(
		err,
	) {
		return errorsNewSchema(
			"tasks.status column does not exist",
		)
	}

	if err != nil {
		return err
	}

	dataType = strings.ToLower(
		strings.TrimSpace(
			dataType,
		),
	)

	columnType = strings.ToLower(
		strings.TrimSpace(
			columnType,
		),
	)

	// =====================================================
	// Already compatible:
	//
	// VARCHAR(32) or larger
	// =====================================================

	if dataType == "varchar" &&
		maxLength.Valid &&
		maxLength.Int64 >= 32 {
		return nil
	}

	// =====================================================
	// Upgrade:
	//
	// ENUM / CHAR / short VARCHAR
	//       ↓
	// VARCHAR(32)
	// =====================================================

	if _, err = db.ExecContext(
		ctx,
		`
		ALTER TABLE tasks
		MODIFY COLUMN status
			VARCHAR(32)
			NOT NULL
			DEFAULT 'RUNNING'
		`,
	); err != nil {
		return fmt.Errorf(
			"upgrade tasks.status from %s failed: %w",
			columnType,
			err,
		)
	}

	return nil
}

// =========================================================
// Tiny local helpers
//
// 保持 mysql.go 不额外暴露 schema error 类型。
// =========================================================

func errorsIsNoRows(
	err error,
) bool {
	return err == sql.ErrNoRows
}

func errorsNewSchema(
	message string,
) error {
	return fmt.Errorf(
		"runtime schema error: %s",
		message,
	)
}
