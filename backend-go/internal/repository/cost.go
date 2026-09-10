package repository

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

func (r *MySQL) RecordRunCost(ctx context.Context, record model.RunCostRecord) error {
	if record.TaskID <= 0 || record.UserID <= 0 {
		return errors.New("invalid run cost identity")
	}
	if record.InputTokens < 0 || record.OutputTokens < 0 || record.TotalTokens < 0 || record.EstimatedCost < 0 {
		return errors.New("invalid run cost values")
	}
	status := strings.TrimSpace(strings.ToLower(record.CostStatus))
	if status != "actual" && status != "estimated" && status != "unavailable" {
		status = "unavailable"
	}
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO run_cost_records(
			task_id,user_id,project_id,provider,model_name,
			input_tokens,output_tokens,total_tokens,estimated_cost,cost_status
		)
		VALUES(?,?,?,?,?,?,?,?,?,?)
		ON DUPLICATE KEY UPDATE
			project_id=COALESCE(VALUES(project_id), project_id),
			provider=IF(VALUES(provider) <> '', VALUES(provider), provider),
			model_name=IF(VALUES(model_name) <> '', VALUES(model_name), model_name),
			input_tokens=input_tokens + VALUES(input_tokens),
			output_tokens=output_tokens + VALUES(output_tokens),
			total_tokens=total_tokens + VALUES(total_tokens),
			estimated_cost=estimated_cost + VALUES(estimated_cost),
			cost_status=CASE
				WHEN cost_status='unavailable' OR VALUES(cost_status)='unavailable' THEN 'unavailable'
				WHEN cost_status='estimated' OR VALUES(cost_status)='estimated' THEN 'estimated'
				ELSE 'actual'
			END,
			updated_at=CURRENT_TIMESTAMP(6)
	`, record.TaskID, record.UserID, record.ProjectID, record.Provider, record.ModelName,
		record.InputTokens, record.OutputTokens, record.TotalTokens, record.EstimatedCost, status)
	return err
}

func (r *MySQL) RunCostByTask(ctx context.Context, uid, taskID int64) (*model.RunCostRecord, error) {
	var item model.RunCostRecord
	var updated time.Time
	err := r.db.QueryRowContext(ctx, `
		SELECT task_id,user_id,project_id,provider,model_name,input_tokens,output_tokens,
		       total_tokens,estimated_cost,cost_status,created_at,updated_at
		FROM run_cost_records
		WHERE task_id=? AND user_id=?
		LIMIT 1
	`, taskID, uid).Scan(
		&item.TaskID, &item.UserID, &item.ProjectID, &item.Provider, &item.ModelName,
		&item.InputTokens, &item.OutputTokens, &item.TotalTokens, &item.EstimatedCost,
		&item.CostStatus, &item.CreatedAt, &updated,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	item.UpdatedAt = &updated
	return &item, nil
}

func (r *MySQL) CostSummary(
	ctx context.Context,
	uid int64,
	projectID *int64,
	query model.CostQuery,
) (model.CostSummary, error) {
	var where []string
	var args []any
	if projectID != nil {
		// Project-wide aggregation is authorized by GovernanceService.RequireRole.
		// Do not also constrain user_id here: organization/project viewers need the
		// complete project cost, including runs created by other project members.
		where = []string{"project_id=?"}
		args = []any{*projectID}
	} else {
		// User summary remains strictly tenant-scoped.
		where = []string{"user_id=?"}
		args = []any{uid}
	}
	if query.From != nil {
		where = append(where, "created_at>=?")
		args = append(args, *query.From)
	}
	if query.To != nil {
		where = append(where, "created_at<?")
		args = append(args, *query.To)
	}
	if query.Provider != "" {
		where = append(where, "provider=?")
		args = append(args, query.Provider)
	}
	if query.ModelName != "" {
		where = append(where, "model_name=?")
		args = append(args, query.ModelName)
	}
	clause := strings.Join(where, " AND ")

	var summary model.CostSummary
	err := r.db.QueryRowContext(ctx, `
		SELECT COUNT(*),
		       COALESCE(SUM(input_tokens),0),
		       COALESCE(SUM(output_tokens),0),
		       COALESCE(SUM(total_tokens),0),
		       COALESCE(SUM(estimated_cost),0),
		       COALESCE(SUM(CASE WHEN cost_status IN ('actual','estimated') THEN 1 ELSE 0 END),0),
		       COALESCE(SUM(CASE WHEN cost_status='unavailable' THEN 1 ELSE 0 END),0)
		FROM run_cost_records
		WHERE `+clause, args...).Scan(
		&summary.RunCount,
		&summary.InputTokens,
		&summary.OutputTokens,
		&summary.TotalTokens,
		&summary.EstimatedCost,
		&summary.KnownCostRuns,
		&summary.UnknownCostRuns,
	)
	if err != nil {
		return model.CostSummary{}, err
	}

	rows, err := r.db.QueryContext(ctx, `
		SELECT provider,model_name,COUNT(*),
		       COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),
		       COALESCE(SUM(total_tokens),0),COALESCE(SUM(estimated_cost),0)
		FROM run_cost_records
		WHERE `+clause+`
		GROUP BY provider,model_name
		ORDER BY SUM(estimated_cost) DESC, SUM(total_tokens) DESC
	`, args...)
	if err != nil {
		return model.CostSummary{}, err
	}
	defer rows.Close()

	summary.Breakdown = []model.CostBreakdown{}
	for rows.Next() {
		var item model.CostBreakdown
		if err := rows.Scan(
			&item.Provider, &item.ModelName, &item.Runs,
			&item.InputTokens, &item.OutputTokens, &item.TotalTokens, &item.EstimatedCost,
		); err != nil {
			return model.CostSummary{}, err
		}
		summary.Breakdown = append(summary.Breakdown, item)
	}
	return summary, rows.Err()
}
