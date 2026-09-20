package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"example.com/agentmesh-control-plane/internal/model"
)

func scanTool(s scanner) (*model.Tool, error) {
	var t model.Tool
	var schema []byte
	var outputSchema []byte
	var sideEffectRisk sql.NullString
	var fallbackToolID sql.NullString
	var argumentAliases []byte
	err := s.Scan(&t.ID, &t.UserID, &t.Name, &t.Description, &t.Protocol, &t.Endpoint, &schema, &t.RiskLevel, &t.RequiresConfirmation, &t.Enabled, &outputSchema, &sideEffectRisk, &t.SupportsIdempotencyKey, &fallbackToolID, &argumentAliases, &t.CreatedAt, &t.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(schema, &t.InputSchema); err != nil {
		return nil, err
	}
	if len(outputSchema) > 0 {
		_ = json.Unmarshal(outputSchema, &t.OutputSchema)
	}
	if sideEffectRisk.Valid && sideEffectRisk.String != "" {
		t.SideEffectRisk = sideEffectRisk.String
	}
	if fallbackToolID.Valid {
		t.FallbackToolID = fallbackToolID.String
	}
	if len(argumentAliases) > 0 {
		_ = json.Unmarshal(argumentAliases, &t.ArgumentAliases)
	}
	return &t, nil
}

const toolColumns = `id,user_id,name,description,protocol,endpoint,input_schema,risk_level,requires_confirmation,enabled,output_schema,side_effect_risk,supports_idempotency_key,fallback_tool_id,argument_aliases,created_at,updated_at`

func marshalJSONColumn(value any) []byte {
	if value == nil {
		return nil
	}
	b, err := json.Marshal(value)
	if err != nil {
		return nil
	}
	return b
}

func nullableJSONColumn(value any) any {
	b := marshalJSONColumn(value)
	if len(b) == 0 {
		return nil
	}
	return string(b)
}

func (r *MySQL) CreateTool(ctx context.Context, uid int64, t model.Tool) (*model.Tool, error) {
	b, _ := json.Marshal(t.InputSchema)
	res, e := r.db.ExecContext(ctx, `INSERT INTO tools(user_id,name,description,protocol,endpoint,input_schema,risk_level,requires_confirmation,enabled,output_schema,side_effect_risk,supports_idempotency_key,fallback_tool_id,argument_aliases) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
		uid, t.Name, t.Description, t.Protocol, t.Endpoint, string(b), t.RiskLevel, t.RequiresConfirmation, t.Enabled,
		nullableJSONColumn(t.OutputSchema), t.SideEffectRisk, t.SupportsIdempotencyKey, t.FallbackToolID, nullableJSONColumn(t.ArgumentAliases))
	if e != nil {
		return nil, e
	}
	id, _ := res.LastInsertId()
	return r.ToolByID(ctx, uid, id)
}
func (r *MySQL) ToolByID(ctx context.Context, uid, id int64) (*model.Tool, error) {
	return scanTool(r.db.QueryRowContext(ctx, `SELECT `+toolColumns+` FROM tools WHERE id=? AND user_id=?`, id, uid))
}
func (r *MySQL) ListTools(ctx context.Context, uid int64, enabledOnly bool) ([]model.Tool, error) {
	q := `SELECT ` + toolColumns + ` FROM tools WHERE user_id=?`
	if enabledOnly {
		q += ` AND enabled=1`
	}
	q += ` ORDER BY id`
	rows, e := r.db.QueryContext(ctx, q, uid)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []model.Tool{}
	for rows.Next() {
		t, e := scanTool(rows)
		if e != nil {
			return nil, e
		}
		out = append(out, *t)
	}
	return out, rows.Err()
}
func (r *MySQL) UpdateTool(ctx context.Context, uid, id int64, t model.Tool) (*model.Tool, error) {
	b, _ := json.Marshal(t.InputSchema)
	res, e := r.db.ExecContext(ctx, `UPDATE tools SET name=?,description=?,protocol=?,endpoint=?,input_schema=?,risk_level=?,requires_confirmation=?,enabled=?,output_schema=?,side_effect_risk=?,supports_idempotency_key=?,fallback_tool_id=?,argument_aliases=? WHERE id=? AND user_id=?`,
		t.Name, t.Description, t.Protocol, t.Endpoint, string(b), t.RiskLevel, t.RequiresConfirmation, t.Enabled,
		nullableJSONColumn(t.OutputSchema), t.SideEffectRisk, t.SupportsIdempotencyKey, t.FallbackToolID, nullableJSONColumn(t.ArgumentAliases), id, uid)
	if e != nil {
		return nil, e
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return nil, nil
	}
	return r.ToolByID(ctx, uid, id)
}
func (r *MySQL) DeleteTool(ctx context.Context, uid, id int64) (bool, error) {
	res, e := r.db.ExecContext(ctx, `DELETE FROM tools WHERE id=? AND user_id=?`, id, uid)
	if e != nil {
		return false, e
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}
