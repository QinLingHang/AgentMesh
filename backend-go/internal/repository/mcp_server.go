package repository

import (
	"context"
	"database/sql"
	"errors"
	"example.com/agentmesh-control-plane/internal/model"
)

const mcpColumns = `id,user_id,name,transport,endpoint,enabled,connect_timeout_ms,call_timeout_ms,created_at,updated_at`

func scanMCPServer(s scanner) (*model.MCPServer, error) {
	var v model.MCPServer
	e := s.Scan(&v.ID, &v.UserID, &v.Name, &v.Transport, &v.Endpoint, &v.Enabled, &v.ConnectTimeoutMS, &v.CallTimeoutMS, &v.CreatedAt, &v.UpdatedAt)
	if errors.Is(e, sql.ErrNoRows) {
		return nil, nil
	}
	return &v, e
}
func (r *MySQL) CreateMCPServer(ctx context.Context, uid int64, v model.MCPServer) (*model.MCPServer, error) {
	res, e := r.db.ExecContext(ctx, `INSERT INTO mcp_servers(user_id,name,transport,endpoint,enabled,connect_timeout_ms,call_timeout_ms) VALUES(?,?,?,?,?,?,?)`, uid, v.Name, v.Transport, v.Endpoint, v.Enabled, v.ConnectTimeoutMS, v.CallTimeoutMS)
	if e != nil {
		return nil, e
	}
	id, _ := res.LastInsertId()
	return r.MCPServerByID(ctx, uid, id)
}
func (r *MySQL) ListMCPServers(ctx context.Context, uid int64, enabled bool) ([]model.MCPServer, error) {
	q := `SELECT ` + mcpColumns + ` FROM mcp_servers WHERE user_id=?`
	if enabled {
		q += ` AND enabled=1`
	}
	q += ` ORDER BY id`
	rows, e := r.db.QueryContext(ctx, q, uid)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []model.MCPServer{}
	for rows.Next() {
		v, e := scanMCPServer(rows)
		if e != nil {
			return nil, e
		}
		out = append(out, *v)
	}
	return out, rows.Err()
}
func (r *MySQL) MCPServerByID(ctx context.Context, uid, id int64) (*model.MCPServer, error) {
	return scanMCPServer(r.db.QueryRowContext(ctx, `SELECT `+mcpColumns+` FROM mcp_servers WHERE id=? AND user_id=?`, id, uid))
}
func (r *MySQL) UpdateMCPServer(ctx context.Context, uid, id int64, v model.MCPServer) (*model.MCPServer, error) {
	res, e := r.db.ExecContext(ctx, `UPDATE mcp_servers SET name=?,transport=?,endpoint=?,enabled=?,connect_timeout_ms=?,call_timeout_ms=? WHERE id=? AND user_id=?`, v.Name, v.Transport, v.Endpoint, v.Enabled, v.ConnectTimeoutMS, v.CallTimeoutMS, id, uid)
	if e != nil {
		return nil, e
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return nil, nil
	}
	return r.MCPServerByID(ctx, uid, id)
}
func (r *MySQL) DeleteMCPServer(ctx context.Context, uid, id int64) (bool, error) {
	res, e := r.db.ExecContext(ctx, `DELETE FROM mcp_servers WHERE id=? AND user_id=?`, id, uid)
	if e != nil {
		return false, e
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}
