package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
)

func (r *MySQL) ensureProjectRuntimeProfile(
	ctx context.Context,
	uid int64,
	projectID int64,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO project_runtime_profiles(
			project_id,
			user_id
		)
		SELECT
			p.id,
			p.user_id
		FROM projects p
		WHERE p.id = ?
		  AND (p.user_id = ? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=?))
		ON DUPLICATE KEY UPDATE
			user_id = VALUES(user_id)
		`,
		projectID,
		uid,
		uid,
	)
	if err != nil {
		return err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return err
	}

	if affected == 0 {
		var exists int64
		err = r.db.QueryRowContext(
			ctx,
			`SELECT p.id FROM projects p WHERE p.id=? AND (p.user_id=? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=?)) LIMIT 1`,
			projectID,
			uid,
			uid,
		).Scan(&exists)

		if errors.Is(err, sql.ErrNoRows) {
			return ErrNotOwned
		}

		return err
	}

	return nil
}

func (r *MySQL) ProjectRuntimeConfig(
	ctx context.Context,
	uid int64,
	projectID int64,
) (*model.ProjectRuntimeConfig, error) {
	if err := r.ensureProjectRuntimeProfile(
		ctx,
		uid,
		projectID,
	); err != nil {
		return nil, err
	}

	var config model.ProjectRuntimeConfig

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			prp.project_id,
			p.user_id,
			prp.agent_mode,
			prp.tool_mode,
			prp.mcp_mode,
			prp.policy_mode,
			prp.scheduler,
			prp.planner,
			prp.execution_mode,
			prp.synthesis_mode,
			prp.max_latency_ms,
			prp.max_cost,
			prp.min_quality,
			prp.created_at,
			prp.updated_at
		FROM project_runtime_profiles prp
		INNER JOIN projects p
			ON p.id = prp.project_id
		WHERE prp.project_id = ?
		  AND prp.user_id = p.user_id
		  AND (p.user_id = ? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=?))
		LIMIT 1
		`,
		projectID,
		uid,
		uid,
	).Scan(
		&config.ProjectID,
		&config.ResourceOwnerID,
		&config.AgentMode,
		&config.ToolMode,
		&config.MCPMode,
		&config.Policy.Mode,
		&config.Policy.Scheduler,
		&config.Policy.Planner,
		&config.Policy.ExecutionMode,
		&config.Policy.SynthesisMode,
		&config.Policy.Constraints.MaxLatencyMS,
		&config.Policy.Constraints.MaxCost,
		&config.Policy.Constraints.MinQuality,
		&config.CreatedAt,
		&config.UpdatedAt,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	config.AgentIDs, err = r.projectBindingIDs(
		ctx,
		`SELECT agent_id FROM project_agent_bindings WHERE project_id=? ORDER BY agent_id`,
		projectID,
	)
	if err != nil {
		return nil, err
	}

	config.ToolIDs, err = r.projectBindingIDs(
		ctx,
		`SELECT tool_id FROM project_tool_bindings WHERE project_id=? ORDER BY tool_id`,
		projectID,
	)
	if err != nil {
		return nil, err
	}

	config.MCPServerIDs, err = r.projectBindingIDs(
		ctx,
		`SELECT mcp_server_id FROM project_mcp_bindings WHERE project_id=? ORDER BY mcp_server_id`,
		projectID,
	)
	if err != nil {
		return nil, err
	}

	return &config, nil
}

func (r *MySQL) projectBindingIDs(
	ctx context.Context,
	query string,
	projectID int64,
) ([]int64, error) {
	rows, err := r.db.QueryContext(
		ctx,
		query,
		projectID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	ids := []int64{}

	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}

	return ids, rows.Err()
}

func sqlPlaceholders(count int) string {
	if count <= 0 {
		return ""
	}

	items := make([]string, count)
	for i := range items {
		items[i] = "?"
	}

	return strings.Join(items, ",")
}

func validateOwnedIDs(
	ctx context.Context,
	tx *sql.Tx,
	table string,
	uid int64,
	ids []int64,
) error {
	if len(ids) == 0 {
		return nil
	}

	idColumn := "id"
	statusClause := ""

	switch table {
	case "agents":
		statusClause = " AND status='ACTIVE'"
	case "tools":
		statusClause = ""
	case "mcp_servers":
		statusClause = ""
	default:
		return fmt.Errorf("unsupported binding table: %s", table)
	}

	args := make([]any, 0, len(ids)+1)
	args = append(args, uid)
	for _, id := range ids {
		args = append(args, id)
	}

	query := fmt.Sprintf(
		"SELECT COUNT(*) FROM %s WHERE user_id=? AND %s IN (%s)%s",
		table,
		idColumn,
		sqlPlaceholders(len(ids)),
		statusClause,
	)

	var count int
	if err := tx.QueryRowContext(
		ctx,
		query,
		args...,
	).Scan(&count); err != nil {
		return err
	}

	if count != len(ids) {
		return ErrNotOwned
	}

	return nil
}

func replaceProjectBindings(
	ctx context.Context,
	tx *sql.Tx,
	projectID int64,
	table string,
	column string,
	ids []int64,
) error {
	if _, err := tx.ExecContext(
		ctx,
		fmt.Sprintf(
			"DELETE FROM %s WHERE project_id=?",
			table,
		),
		projectID,
	); err != nil {
		return err
	}

	if len(ids) == 0 {
		return nil
	}

	for _, id := range ids {
		if _, err := tx.ExecContext(
			ctx,
			fmt.Sprintf(
				"INSERT INTO %s(project_id,%s) VALUES(?,?)",
				table,
				column,
			),
			projectID,
			id,
		); err != nil {
			return err
		}
	}

	return nil
}

func (r *MySQL) UpdateProjectRuntimeConfig(
	ctx context.Context,
	uid int64,
	config model.ProjectRuntimeConfig,
) (*model.ProjectRuntimeConfig, error) {
	tx, err := r.db.BeginTx(
		ctx,
		nil,
	)
	if err != nil {
		return nil, err
	}
	defer func() {
		_ = tx.Rollback()
	}()

	var owned int64
	if err = tx.QueryRowContext(
		ctx,
		`SELECT id FROM projects WHERE id=? AND user_id=? LIMIT 1 FOR UPDATE`,
		config.ProjectID,
		uid,
	).Scan(&owned); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotOwned
	} else if err != nil {
		return nil, err
	}

	if err = validateOwnedIDs(
		ctx,
		tx,
		"agents",
		uid,
		config.AgentIDs,
	); err != nil {
		return nil, err
	}

	if err = validateOwnedIDs(
		ctx,
		tx,
		"tools",
		uid,
		config.ToolIDs,
	); err != nil {
		return nil, err
	}

	if err = validateOwnedIDs(
		ctx,
		tx,
		"mcp_servers",
		uid,
		config.MCPServerIDs,
	); err != nil {
		return nil, err
	}

	_, err = tx.ExecContext(
		ctx,
		`
		INSERT INTO project_runtime_profiles(
			project_id,
			user_id,
			agent_mode,
			tool_mode,
			mcp_mode,
			policy_mode,
			scheduler,
			planner,
			execution_mode,
			synthesis_mode,
			max_latency_ms,
			max_cost,
			min_quality
		)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
		ON DUPLICATE KEY UPDATE
			user_id=VALUES(user_id),
			agent_mode=VALUES(agent_mode),
			tool_mode=VALUES(tool_mode),
			mcp_mode=VALUES(mcp_mode),
			policy_mode=VALUES(policy_mode),
			scheduler=VALUES(scheduler),
			planner=VALUES(planner),
			execution_mode=VALUES(execution_mode),
			synthesis_mode=VALUES(synthesis_mode),
			max_latency_ms=VALUES(max_latency_ms),
			max_cost=VALUES(max_cost),
			min_quality=VALUES(min_quality),
			updated_at=CURRENT_TIMESTAMP(6)
		`,
		config.ProjectID,
		uid,
		config.AgentMode,
		config.ToolMode,
		config.MCPMode,
		config.Policy.Mode,
		config.Policy.Scheduler,
		config.Policy.Planner,
		config.Policy.ExecutionMode,
		config.Policy.SynthesisMode,
		config.Policy.Constraints.MaxLatencyMS,
		config.Policy.Constraints.MaxCost,
		config.Policy.Constraints.MinQuality,
	)
	if err != nil {
		return nil, err
	}

	if err = replaceProjectBindings(
		ctx,
		tx,
		config.ProjectID,
		"project_agent_bindings",
		"agent_id",
		config.AgentIDs,
	); err != nil {
		return nil, err
	}

	if err = replaceProjectBindings(
		ctx,
		tx,
		config.ProjectID,
		"project_tool_bindings",
		"tool_id",
		config.ToolIDs,
	); err != nil {
		return nil, err
	}

	if err = replaceProjectBindings(
		ctx,
		tx,
		config.ProjectID,
		"project_mcp_bindings",
		"mcp_server_id",
		config.MCPServerIDs,
	); err != nil {
		return nil, err
	}

	if err = tx.Commit(); err != nil {
		return nil, err
	}

	return r.ProjectRuntimeConfig(
		ctx,
		uid,
		config.ProjectID,
	)
}

func (r *MySQL) ProjectIDByConversation(
	ctx context.Context,
	uid int64,
	conversationID int64,
) (*int64, error) {
	var projectID int64

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT pc.project_id
		FROM project_conversations pc
		INNER JOIN projects p
			ON p.id = pc.project_id
		INNER JOIN conversations c
			ON c.id = pc.conversation_id
		WHERE pc.conversation_id = ?
		  AND (p.user_id = ? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=?))
		  AND c.user_id = ?
		LIMIT 1
		`,
		conversationID,
		uid,
		uid,
		uid,
	).Scan(&projectID)

	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &projectID, nil
}
