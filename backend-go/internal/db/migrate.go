package db

import (
	"context"
	"database/sql"
	"fmt"
)

// Migrate applies every incremental schema owned by the Go control plane.
//
// The base schema is still initialized by infra/mysql/init/001_schema.sql for a
// brand-new MySQL volume. This function is the authoritative upgrade path for
// existing databases and is intentionally idempotent so it can be invoked by
// both the production migration job and the server startup safety net.
func Migrate(ctx context.Context, database *sql.DB) error {
	steps := []struct {
		name string
		fn   func(context.Context, *sql.DB) error
	}{
		{name: "runtime", fn: ensureRuntimeSchema},
		{name: "workspace", fn: EnsureWorkspaceSchema},
		{name: "project_runtime", fn: EnsureProjectRuntimeSchema},
		{name: "memory", fn: EnsureMemorySchema},
		{name: "governance", fn: EnsureGovernanceSchema},
		{name: "user_model", fn: EnsureUserModelSchema},
		{name: "attachments", fn: EnsureAttachmentSchema},
		{name: "v2_intelligence", fn: EnsureV2IntelligenceSchema},
	}

	for _, step := range steps {
		if err := step.fn(ctx, database); err != nil {
			return fmt.Errorf("%s migration failed: %w", step.name, err)
		}
	}

	return nil
}
