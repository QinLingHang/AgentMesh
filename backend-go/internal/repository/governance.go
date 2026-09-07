package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

func normalizeRole(role string) string {
	switch role {
	case "OWNER", "ADMIN", "DEVELOPER", "VIEWER":
		return role
	default:
		return ""
	}
}

func (r *MySQL) ProjectRole(ctx context.Context, uid, projectID int64) (string, error) {
	var ownerID int64
	if err := r.db.QueryRowContext(ctx, `SELECT user_id FROM projects WHERE id=? LIMIT 1`, projectID).Scan(&ownerID); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return "", nil
		}
		return "", err
	}
	if ownerID == uid {
		return "OWNER", nil
	}
	var role string
	err := r.db.QueryRowContext(ctx, `SELECT role FROM project_members WHERE project_id=? AND user_id=? LIMIT 1`, projectID, uid).Scan(&role)
	if errors.Is(err, sql.ErrNoRows) {
		return "", nil
	}
	return role, err
}

func (r *MySQL) ListProjectMembers(ctx context.Context, projectID int64) ([]model.ProjectMember, error) {
	rows, err := r.db.QueryContext(ctx, `
		SELECT pm.project_id,pm.user_id,u.email,u.display_name,pm.role,pm.created_at,pm.updated_at
		FROM project_members pm INNER JOIN users u ON u.id=pm.user_id
		WHERE pm.project_id=? ORDER BY pm.created_at,pm.user_id`, projectID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.ProjectMember{}
	for rows.Next() {
		var item model.ProjectMember
		if err := rows.Scan(&item.ProjectID, &item.UserID, &item.Email, &item.DisplayName, &item.Role, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (r *MySQL) UpsertProjectMemberByEmail(ctx context.Context, projectID int64, email, role string) (*model.ProjectMember, error) {
	var uid int64
	if err := r.db.QueryRowContext(ctx, `SELECT id FROM users WHERE email=? AND status='ACTIVE' LIMIT 1`, email).Scan(&uid); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	if _, err := r.db.ExecContext(ctx, `INSERT INTO project_members(project_id,user_id,role) VALUES(?,?,?) ON DUPLICATE KEY UPDATE role=VALUES(role),updated_at=CURRENT_TIMESTAMP(6)`, projectID, uid, role); err != nil {
		return nil, err
	}
	var item model.ProjectMember
	err := r.db.QueryRowContext(ctx, `SELECT pm.project_id,pm.user_id,u.email,u.display_name,pm.role,pm.created_at,pm.updated_at FROM project_members pm INNER JOIN users u ON u.id=pm.user_id WHERE pm.project_id=? AND pm.user_id=?`, projectID, uid).Scan(&item.ProjectID, &item.UserID, &item.Email, &item.DisplayName, &item.Role, &item.CreatedAt, &item.UpdatedAt)
	return &item, err
}

func (r *MySQL) DeleteProjectMember(ctx context.Context, projectID, memberUID int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM project_members WHERE project_id=? AND user_id=?`, projectID, memberUID)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	return n > 0, err
}

func (r *MySQL) GetProjectQuota(ctx context.Context, projectID int64) (model.ProjectQuota, error) {
	_, _ = r.db.ExecContext(ctx, `INSERT IGNORE INTO project_quotas(project_id) VALUES(?)`, projectID)
	var q model.ProjectQuota
	err := r.db.QueryRowContext(ctx, `SELECT project_id,requests_per_minute,concurrent_tasks,monthly_token_limit,monthly_cost_limit,daily_tool_action_limit FROM project_quotas WHERE project_id=?`, projectID).Scan(&q.ProjectID, &q.RequestsPerMinute, &q.ConcurrentTasks, &q.MonthlyTokenLimit, &q.MonthlyCostLimit, &q.DailyToolActionLimit)
	return q, err
}

func (r *MySQL) UpsertProjectQuota(ctx context.Context, q model.ProjectQuota) (model.ProjectQuota, error) {
	_, err := r.db.ExecContext(ctx, `INSERT INTO project_quotas(project_id,requests_per_minute,concurrent_tasks,monthly_token_limit,monthly_cost_limit,daily_tool_action_limit) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE requests_per_minute=VALUES(requests_per_minute),concurrent_tasks=VALUES(concurrent_tasks),monthly_token_limit=VALUES(monthly_token_limit),monthly_cost_limit=VALUES(monthly_cost_limit),daily_tool_action_limit=VALUES(daily_tool_action_limit)`, q.ProjectID, q.RequestsPerMinute, q.ConcurrentTasks, q.MonthlyTokenLimit, q.MonthlyCostLimit, q.DailyToolActionLimit)
	if err != nil {
		return model.ProjectQuota{}, err
	}
	return r.GetProjectQuota(ctx, q.ProjectID)
}

func (r *MySQL) GetProjectUsage(ctx context.Context, projectID int64) (model.ProjectUsage, error) {
	month := time.Now().UTC().Format("2006-01")
	_, _ = r.db.ExecContext(ctx, `INSERT IGNORE INTO project_usage_monthly(project_id,month_key) VALUES(?,?)`, projectID, month)
	var u model.ProjectUsage
	err := r.db.QueryRowContext(ctx, `SELECT project_id,month_key,request_count,token_count,estimated_cost,tool_action_count FROM project_usage_monthly WHERE project_id=? AND month_key=?`, projectID, month).Scan(&u.ProjectID, &u.MonthKey, &u.RequestCount, &u.TokenCount, &u.EstimatedCost, &u.ToolActionCount)
	if err != nil {
		return u, err
	}
	_ = r.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM tasks t INNER JOIN project_conversations pc ON pc.conversation_id=t.conversation_id WHERE pc.project_id=? AND t.status IN ('QUEUED','RUNNING','INPUT_REQUIRED','AUTH_REQUIRED')`, projectID).Scan(&u.ConcurrentTasks)
	return u, nil
}

func (r *MySQL) CreateProjectSecret(ctx context.Context, item model.ProjectSecret, ciphertext, nonce []byte) (*model.ProjectSecret, error) {
	res, err := r.db.ExecContext(ctx, `INSERT INTO project_secrets(project_id,name,kind,ciphertext,nonce,masked_hint,created_by) VALUES(?,?,?,?,?,?,?)`, item.ProjectID, item.Name, item.Kind, ciphertext, nonce, item.MaskedHint, item.CreatedBy)
	if err != nil {
		return nil, err
	}
	id, _ := res.LastInsertId()
	return r.ProjectSecretByID(ctx, item.ProjectID, id)
}
func (r *MySQL) ProjectSecretByID(ctx context.Context, projectID, id int64) (*model.ProjectSecret, error) {
	var s model.ProjectSecret
	var last sql.NullTime
	err := r.db.QueryRowContext(ctx, `SELECT id,project_id,name,kind,masked_hint,created_by,created_at,updated_at,last_used_at FROM project_secrets WHERE project_id=? AND id=?`, projectID, id).Scan(&s.ID, &s.ProjectID, &s.Name, &s.Kind, &s.MaskedHint, &s.CreatedBy, &s.CreatedAt, &s.UpdatedAt, &last)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if last.Valid {
		s.LastUsedAt = &last.Time
	}
	return &s, nil
}
func (r *MySQL) ListProjectSecrets(ctx context.Context, projectID int64) ([]model.ProjectSecret, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id,project_id,name,kind,masked_hint,created_by,created_at,updated_at,last_used_at FROM project_secrets WHERE project_id=? ORDER BY updated_at DESC,id DESC`, projectID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.ProjectSecret{}
	for rows.Next() {
		var s model.ProjectSecret
		var last sql.NullTime
		if err := rows.Scan(&s.ID, &s.ProjectID, &s.Name, &s.Kind, &s.MaskedHint, &s.CreatedBy, &s.CreatedAt, &s.UpdatedAt, &last); err != nil {
			return nil, err
		}
		if last.Valid {
			s.LastUsedAt = &last.Time
		}
		out = append(out, s)
	}
	return out, rows.Err()
}
func (r *MySQL) SecretCiphertext(ctx context.Context, projectID, id int64) ([]byte, []byte, error) {
	var c, n []byte
	err := r.db.QueryRowContext(ctx, `SELECT ciphertext,nonce FROM project_secrets WHERE project_id=? AND id=?`, projectID, id).Scan(&c, &n)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, nil
	}
	return c, n, err
}
func (r *MySQL) DeleteProjectSecret(ctx context.Context, projectID, id int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM project_secrets WHERE project_id=? AND id=?`, projectID, id)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

func (r *MySQL) UpsertProjectModelProvider(ctx context.Context, p model.ProjectModelProvider) (*model.ProjectModelProvider, error) {
	_, err := r.db.ExecContext(ctx, `INSERT INTO project_model_providers(project_id,provider,base_url,model_name,secret_id,enabled) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE provider=VALUES(provider),base_url=VALUES(base_url),model_name=VALUES(model_name),secret_id=VALUES(secret_id),enabled=VALUES(enabled),updated_at=CURRENT_TIMESTAMP(6)`, p.ProjectID, p.Provider, p.BaseURL, p.ModelName, p.SecretID, p.Enabled)
	if err != nil {
		return nil, err
	}
	return r.GetProjectModelProvider(ctx, p.ProjectID)
}
func (r *MySQL) GetProjectModelProvider(ctx context.Context, projectID int64) (*model.ProjectModelProvider, error) {
	var p model.ProjectModelProvider
	var secret sql.NullInt64
	err := r.db.QueryRowContext(ctx, `SELECT project_id,provider,base_url,model_name,secret_id,enabled,created_at,updated_at FROM project_model_providers WHERE project_id=?`, projectID).Scan(&p.ProjectID, &p.Provider, &p.BaseURL, &p.ModelName, &secret, &p.Enabled, &p.CreatedAt, &p.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if secret.Valid {
		p.SecretID = &secret.Int64
	}
	return &p, nil
}

func (r *MySQL) AppendAudit(ctx context.Context, e model.AuditEvent) error {
	b, _ := json.Marshal(e.Metadata)
	_, err := r.db.ExecContext(ctx, `INSERT INTO audit_events(project_id,actor_user_id,action,resource_type,resource_id,result,metadata_json) VALUES(?,?,?,?,?,?,?)`, e.ProjectID, e.ActorUserID, e.Action, e.ResourceType, e.ResourceID, e.Result, b)
	return err
}
func (r *MySQL) ListAudit(ctx context.Context, projectID int64, limit int) ([]model.AuditEvent, error) {
	if limit <= 0 || limit > 200 {
		limit = 100
	}
	rows, err := r.db.QueryContext(ctx, `SELECT id,project_id,actor_user_id,action,resource_type,resource_id,result,metadata_json,created_at FROM audit_events WHERE project_id=? ORDER BY id DESC LIMIT ?`, projectID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.AuditEvent{}
	for rows.Next() {
		var e model.AuditEvent
		var pid sql.NullInt64
		var raw []byte
		if err := rows.Scan(&e.ID, &pid, &e.ActorUserID, &e.Action, &e.ResourceType, &e.ResourceID, &e.Result, &raw, &e.CreatedAt); err != nil {
			return nil, err
		}
		if pid.Valid {
			e.ProjectID = &pid.Int64
		}
		_ = json.Unmarshal(raw, &e.Metadata)
		out = append(out, e)
	}
	return out, rows.Err()
}

func (r *MySQL) ConsumeProjectRequest(ctx context.Context, projectID, limit int64) (bool, error) {
	minute := time.Now().UTC().Format("2006-01-02T15:04")
	_, err := r.db.ExecContext(ctx, `INSERT INTO project_request_windows(project_id,minute_key,request_count) VALUES(?,?,1) ON DUPLICATE KEY UPDATE request_count=request_count+1,updated_at=CURRENT_TIMESTAMP(6)`, projectID, minute)
	if err != nil {
		return false, err
	}
	var count int64
	if err := r.db.QueryRowContext(ctx, `SELECT request_count FROM project_request_windows WHERE project_id=? AND minute_key=?`, projectID, minute).Scan(&count); err != nil {
		return false, err
	}
	return count <= limit, nil
}

func (r *MySQL) DailyToolActions(ctx context.Context, projectID int64) (int64, error) {
	day := time.Now().UTC().Format("2006-01-02")
	var count int64
	err := r.db.QueryRowContext(ctx, `SELECT tool_action_count FROM project_usage_daily WHERE project_id=? AND day_key=?`, projectID, day).Scan(&count)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, nil
	}
	return count, err
}

func (r *MySQL) RecordProjectUsage(ctx context.Context, projectID int64, tokens int64, cost float64, toolActions int64) error {
	month := time.Now().UTC().Format("2006-01")
	day := time.Now().UTC().Format("2006-01-02")
	_, err := r.db.ExecContext(ctx, `INSERT INTO project_usage_monthly(project_id,month_key,request_count,token_count,estimated_cost,tool_action_count) VALUES(?,?,0,?,?,?) ON DUPLICATE KEY UPDATE token_count=token_count+VALUES(token_count),estimated_cost=estimated_cost+VALUES(estimated_cost),tool_action_count=tool_action_count+VALUES(tool_action_count),updated_at=CURRENT_TIMESTAMP(6)`, projectID, month, tokens, cost, toolActions)
	if err != nil {
		return err
	}
	_, err = r.db.ExecContext(ctx, `INSERT INTO project_usage_daily(project_id,day_key,tool_action_count) VALUES(?,?,?) ON DUPLICATE KEY UPDATE tool_action_count=tool_action_count+VALUES(tool_action_count),updated_at=CURRENT_TIMESTAMP(6)`, projectID, day, toolActions)
	return err
}

func (r *MySQL) CreateOrganization(ctx context.Context, ownerID int64, name string) (*model.Organization, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	res, err := tx.ExecContext(ctx, `INSERT INTO organizations(owner_user_id,name) VALUES(?,?)`, ownerID, name)
	if err != nil {
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO organization_members(organization_id,user_id,role) VALUES(?,?,'OWNER')`, id, ownerID); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	var o model.Organization
	err = r.db.QueryRowContext(ctx, `SELECT id,owner_user_id,name,created_at,updated_at FROM organizations WHERE id=?`, id).Scan(&o.ID, &o.OwnerID, &o.Name, &o.CreatedAt, &o.UpdatedAt)
	return &o, err
}
func (r *MySQL) ListOrganizations(ctx context.Context, uid int64) ([]model.Organization, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT DISTINCT o.id,o.owner_user_id,o.name,o.created_at,o.updated_at FROM organizations o INNER JOIN organization_members om ON om.organization_id=o.id WHERE om.user_id=? ORDER BY o.updated_at DESC,o.id DESC`, uid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.Organization{}
	for rows.Next() {
		var o model.Organization
		if err := rows.Scan(&o.ID, &o.OwnerID, &o.Name, &o.CreatedAt, &o.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	return out, rows.Err()
}
func (r *MySQL) OrganizationRole(ctx context.Context, uid, orgID int64) (string, error) {
	var role string
	err := r.db.QueryRowContext(ctx, `SELECT role FROM organization_members WHERE organization_id=? AND user_id=? LIMIT 1`, orgID, uid).Scan(&role)
	if errors.Is(err, sql.ErrNoRows) {
		return "", nil
	}
	return role, err
}
func (r *MySQL) UpsertOrganizationMemberByEmail(ctx context.Context, orgID int64, email, role string) (*model.OrganizationMember, error) {
	var uid int64
	if err := r.db.QueryRowContext(ctx, `SELECT id FROM users WHERE email=? AND status='ACTIVE' LIMIT 1`, email).Scan(&uid); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	_, err := r.db.ExecContext(ctx, `INSERT INTO organization_members(organization_id,user_id,role) VALUES(?,?,?) ON DUPLICATE KEY UPDATE role=VALUES(role),updated_at=CURRENT_TIMESTAMP(6)`, orgID, uid, role)
	if err != nil {
		return nil, err
	}
	var m model.OrganizationMember
	err = r.db.QueryRowContext(ctx, `SELECT om.organization_id,om.user_id,u.email,u.display_name,om.role,om.created_at,om.updated_at FROM organization_members om JOIN users u ON u.id=om.user_id WHERE om.organization_id=? AND om.user_id=?`, orgID, uid).Scan(&m.OrganizationID, &m.UserID, &m.Email, &m.DisplayName, &m.Role, &m.CreatedAt, &m.UpdatedAt)
	return &m, err
}
func (r *MySQL) BindProjectToOrganization(ctx context.Context, orgID, projectID, ownerID int64) error {
	// 1. Repository 层再次确认项目所有权。
	// Service 层虽然已经检查过 OWNER，
	// 但 Repository 仍保留这一层防御，避免绕过 Service 直接调用。
	var actualOwnerID int64
	err := r.db.QueryRowContext(
		ctx,
		`SELECT user_id
		 FROM projects
		 WHERE id=?
		 LIMIT 1`,
		projectID,
	).Scan(&actualOwnerID)

	if errors.Is(err, sql.ErrNoRows) {
		return ErrNotOwned
	}
	if err != nil {
		return err
	}
	if actualOwnerID != ownerID {
		return ErrNotOwned
	}

	// 2. 尝试建立关联。
	//
	// project_id 是 organization_projects 的主键，
	// 所以一个项目同一时间只能属于一个工作空间。
	//
	// 如果已经存在，则故意做 no-op，
	// 绝不能在这里直接修改 organization_id，
	// 否则普通“关联”操作会变成静默“迁移项目”。
	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO organization_projects(
			organization_id,
			project_id
		)
		VALUES (?, ?)
		ON DUPLICATE KEY UPDATE
			project_id=VALUES(project_id)`,
		orgID,
		projectID,
	)
	if err != nil {
		return err
	}

	// 3. 查询最终实际归属。
	//
	// 这样同时解决：
	// - 第一次绑定
	// - 重复绑定同一个组织
	// - 并发绑定不同组织
	var boundOrgID int64
	err = r.db.QueryRowContext(
		ctx,
		`SELECT organization_id
		 FROM organization_projects
		 WHERE project_id=?
		 LIMIT 1`,
		projectID,
	).Scan(&boundOrgID)
	if err != nil {
		return err
	}

	// 已经属于当前工作空间：PUT 幂等成功。
	if boundOrgID == orgID {
		return nil
	}

	// 已经属于其他工作空间：
	// 普通绑定接口不得静默迁移。
	return ErrProjectAlreadyBound
}
