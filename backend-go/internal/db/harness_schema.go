package db

import (
	"context"
	"database/sql"
)

// EnsureHarnessSchema applies the P37 Agent Harness schema additions:
//
//   - ToolDefinition contract extensions (outputSchema, side-effect risk,
//     idempotency-key support, explicit fallback tool, argument aliases).
//   - tasks.harness_config_json storing the frozen per-run supervision
//     snapshot created with the task (queue/restart/resume/replay parity).
//
// Legacy rows read as OFF / UNKNOWN, so every addition is nullable or has a
// backward-compatible default and no backfill is required.
func EnsureHarnessSchema(ctx context.Context, db *sql.DB) error {
	toolContract := []struct {
		column string
		ddl    string
	}{
		{
			column: "output_schema",
			ddl:    "ALTER TABLE tools ADD COLUMN output_schema JSON NULL AFTER requires_confirmation",
		},
		{
			column: "side_effect_risk",
			ddl:    "ALTER TABLE tools ADD COLUMN side_effect_risk VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN' AFTER output_schema",
		},
		{
			column: "supports_idempotency_key",
			ddl:    "ALTER TABLE tools ADD COLUMN supports_idempotency_key TINYINT(1) NOT NULL DEFAULT 0 AFTER side_effect_risk",
		},
		{
			column: "fallback_tool_id",
			ddl:    "ALTER TABLE tools ADD COLUMN fallback_tool_id VARCHAR(191) NULL AFTER supports_idempotency_key",
		},
		{
			column: "argument_aliases",
			ddl:    "ALTER TABLE tools ADD COLUMN argument_aliases JSON NULL AFTER fallback_tool_id",
		},
	}

	for _, item := range toolContract {
		if err := ensureColumn(ctx, db, "tools", item.column, item.ddl); err != nil {
			return err
		}
	}

	// Agents: execution framework discriminator. Existing agents keep
	// 'native' behaviour without any data change.
	if err := ensureColumn(
		ctx,
		db,
		"agents",
		"executor_type",
		`ALTER TABLE agents ADD COLUMN executor_type VARCHAR(32) NOT NULL DEFAULT 'native' AFTER protocol`,
	); err != nil {
		return err
	}

	if err := ensureColumn(
		ctx,
		db,
		"tasks",
		"harness_config_json",
		`ALTER TABLE tasks ADD COLUMN harness_config_json JSON NULL AFTER model_selection_json`,
	); err != nil {
		return err
	}

	return nil
}
