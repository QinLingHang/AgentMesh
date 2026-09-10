package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

func decodeStringList(raw []byte) []string {
	out := []string{}
	_ = json.Unmarshal(raw, &out)
	if out == nil {
		return []string{}
	}
	return out
}

func decodeMap(raw []byte) map[string]any {
	out := map[string]any{}
	_ = json.Unmarshal(raw, &out)
	if out == nil {
		return map[string]any{}
	}
	return out
}

func scanServiceAccount(s scanner) (*model.ServiceAccount, string, error) {
	var item model.ServiceAccount
	var scopes []byte
	var expires, lastUsed sql.NullTime
	var secretHash string
	if err := s.Scan(
		&item.ID,
		&item.ProjectID,
		&item.Name,
		&item.KeyPrefix,
		&secretHash,
		&scopes,
		&item.Status,
		&item.CreatedBy,
		&expires,
		&lastUsed,
		&item.RequestCount,
		&item.ErrorCount,
		&item.CreatedAt,
		&item.UpdatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, "", nil
		}
		return nil, "", err
	}
	item.Scopes = decodeStringList(scopes)
	if expires.Valid {
		item.ExpiresAt = &expires.Time
	}
	if lastUsed.Valid {
		item.LastUsedAt = &lastUsed.Time
	}
	return &item, secretHash, nil
}

const serviceAccountSelect = `
SELECT
    sa.id,sa.project_id,sa.name,sa.key_prefix,sa.secret_hash,sa.scopes_json,
    sa.status,sa.created_by,sa.expires_at,sa.last_used_at,
    COALESCE((SELECT SUM(u.request_count) FROM api_usage_daily u WHERE u.service_account_id=sa.id),0),
    COALESCE((SELECT SUM(u.error_count) FROM api_usage_daily u WHERE u.service_account_id=sa.id),0),
    sa.created_at,sa.updated_at
FROM api_service_accounts sa`

func (r *MySQL) CreateServiceAccount(ctx context.Context, item model.ServiceAccount, secretHash string) (*model.ServiceAccount, error) {
	scopes, _ := json.Marshal(item.Scopes)
	res, err := r.db.ExecContext(ctx, `
        INSERT INTO api_service_accounts(project_id,name,key_prefix,secret_hash,scopes_json,status,created_by,expires_at)
        VALUES(?,?,?,?,?,'ACTIVE',?,?)`,
		item.ProjectID, item.Name, item.KeyPrefix, secretHash, scopes, item.CreatedBy, item.ExpiresAt,
	)
	if err != nil {
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	return r.ServiceAccountByID(ctx, item.ProjectID, id)
}

func (r *MySQL) ServiceAccountByID(ctx context.Context, projectID, id int64) (*model.ServiceAccount, error) {
	item, _, err := scanServiceAccount(r.db.QueryRowContext(ctx, serviceAccountSelect+` WHERE sa.project_id=? AND sa.id=? LIMIT 1`, projectID, id))
	return item, err
}

func (r *MySQL) ServiceAccountByPrefix(ctx context.Context, prefix string) (*model.ServiceAccount, string, error) {
	return scanServiceAccount(r.db.QueryRowContext(ctx, serviceAccountSelect+` WHERE sa.key_prefix=? LIMIT 1`, prefix))
}

func (r *MySQL) ListServiceAccounts(ctx context.Context, projectID int64) ([]model.ServiceAccount, error) {
	rows, err := r.db.QueryContext(ctx, serviceAccountSelect+` WHERE sa.project_id=? ORDER BY sa.created_at DESC,sa.id DESC`, projectID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.ServiceAccount{}
	for rows.Next() {
		item, _, err := scanServiceAccount(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *item)
	}
	return out, rows.Err()
}

func (r *MySQL) RevokeServiceAccount(ctx context.Context, projectID, id int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `UPDATE api_service_accounts SET status='REVOKED',updated_at=CURRENT_TIMESTAMP(6) WHERE project_id=? AND id=? AND status<>'REVOKED'`, projectID, id)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	return n > 0, err
}

func (r *MySQL) TouchServiceAccount(ctx context.Context, id int64) error {
	_, err := r.db.ExecContext(ctx, `UPDATE api_service_accounts SET last_used_at=UTC_TIMESTAMP(6) WHERE id=?`, id)
	return err
}

func (r *MySQL) RecordAPIUsage(ctx context.Context, serviceAccountID, projectID int64, statusCode int, latencyMS int64) error {
	day := time.Now().UTC().Format("2006-01-02")
	errorsCount := 0
	if statusCode >= 400 {
		errorsCount = 1
	}
	_, err := r.db.ExecContext(ctx, `
        INSERT INTO api_usage_daily(service_account_id,project_id,day_key,request_count,error_count,latency_ms_total)
        VALUES(?,?,?,1,?,?)
        ON DUPLICATE KEY UPDATE
          request_count=request_count+1,
          error_count=error_count+VALUES(error_count),
          latency_ms_total=latency_ms_total+VALUES(latency_ms_total),
          updated_at=CURRENT_TIMESTAMP(6)`, serviceAccountID, projectID, day, errorsCount, latencyMS)
	return err
}

func (r *MySQL) APIIdempotencyRecord(ctx context.Context, serviceAccountID int64, key string) (*model.APIIdempotencyRecord, error) {
	var item model.APIIdempotencyRecord
	var response sql.NullString
	err := r.db.QueryRowContext(ctx, `SELECT service_account_id,idempotency_key,request_hash,response_json,status,created_at FROM api_idempotency_records WHERE service_account_id=? AND idempotency_key=? LIMIT 1`, serviceAccountID, key).Scan(&item.ServiceAccountID, &item.IdempotencyKey, &item.RequestHash, &response, &item.Status, &item.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if response.Valid {
		item.ResponseJSON = []byte(response.String)
	}
	return &item, nil
}

func (r *MySQL) ReserveAPIIdempotencyRecord(ctx context.Context, item model.APIIdempotencyRecord) (bool, error) {
	res, err := r.db.ExecContext(ctx, `INSERT IGNORE INTO api_idempotency_records(service_account_id,idempotency_key,request_hash,response_json,status) VALUES(?,?,?,NULL,'IN_PROGRESS')`, item.ServiceAccountID, item.IdempotencyKey, item.RequestHash)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	return n > 0, err
}

func (r *MySQL) CompleteAPIIdempotencyRecord(ctx context.Context, serviceAccountID int64, key string, responseJSON []byte) error {
	_, err := r.db.ExecContext(ctx, `UPDATE api_idempotency_records SET response_json=?,status='COMPLETED' WHERE service_account_id=? AND idempotency_key=?`, responseJSON, serviceAccountID, key)
	return err
}

func (r *MySQL) DeleteAPIIdempotencyReservation(ctx context.Context, serviceAccountID int64, key string) error {
	_, err := r.db.ExecContext(ctx, `DELETE FROM api_idempotency_records WHERE service_account_id=? AND idempotency_key=? AND status='IN_PROGRESS'`, serviceAccountID, key)
	return err
}

func scanEcosystemPackage(s scanner) (*model.EcosystemPackage, error) {
	var item model.EcosystemPackage
	if err := s.Scan(&item.ID, &item.OwnerUserID, &item.Slug, &item.Name, &item.Kind, &item.Summary, &item.Description, &item.Visibility, &item.Status, &item.LatestVersion, &item.InstallCount, &item.CreatedAt, &item.UpdatedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return &item, nil
}

const ecosystemPackageSelect = `SELECT id,owner_user_id,slug,name,kind,summary,description,visibility,status,latest_version,install_count,created_at,updated_at FROM ecosystem_packages`

func (r *MySQL) CreateEcosystemPackage(ctx context.Context, item model.EcosystemPackage) (*model.EcosystemPackage, error) {
	res, err := r.db.ExecContext(ctx, `
        INSERT INTO ecosystem_packages(owner_user_id,slug,name,kind,summary,description,visibility,status)
        VALUES(?,?,?,?,?,?,?,'DRAFT')`, item.OwnerUserID, item.Slug, item.Name, item.Kind, item.Summary, item.Description, item.Visibility)
	if err != nil {
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	return r.EcosystemPackageByID(ctx, id)
}

func (r *MySQL) EcosystemPackageByID(ctx context.Context, id int64) (*model.EcosystemPackage, error) {
	return scanEcosystemPackage(r.db.QueryRowContext(ctx, ecosystemPackageSelect+` WHERE id=? LIMIT 1`, id))
}

func (r *MySQL) EcosystemPackageBySlug(ctx context.Context, slug string) (*model.EcosystemPackage, error) {
	return scanEcosystemPackage(r.db.QueryRowContext(ctx, ecosystemPackageSelect+` WHERE slug=? LIMIT 1`, slug))
}

func (r *MySQL) SearchEcosystemPackages(ctx context.Context, query, kind string, includeOwnedBy *int64, limit int) ([]model.EcosystemPackage, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	where := `(status='PUBLISHED' AND visibility='PUBLIC')`
	args := []any{}
	if includeOwnedBy != nil {
		where = `((status='PUBLISHED' AND visibility='PUBLIC') OR owner_user_id=?)`
		args = append(args, *includeOwnedBy)
	}
	if strings.TrimSpace(query) != "" {
		where += ` AND (slug LIKE ? OR name LIKE ? OR summary LIKE ?)`
		like := "%" + strings.TrimSpace(query) + "%"
		args = append(args, like, like, like)
	}
	if strings.TrimSpace(kind) != "" {
		where += ` AND kind=?`
		args = append(args, strings.ToUpper(strings.TrimSpace(kind)))
	}
	args = append(args, limit)
	rows, err := r.db.QueryContext(ctx, ecosystemPackageSelect+` WHERE `+where+` ORDER BY install_count DESC,updated_at DESC,id DESC LIMIT ?`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.EcosystemPackage{}
	for rows.Next() {
		item, err := scanEcosystemPackage(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *item)
	}
	return out, rows.Err()
}

func scanEcosystemVersion(s scanner) (*model.EcosystemPackageVersion, error) {
	var item model.EcosystemPackageVersion
	var manifestRaw []byte
	if err := s.Scan(&item.ID, &item.PackageID, &item.Version, &manifestRaw, &item.Checksum, &item.Status, &item.CreatedBy, &item.CreatedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	_ = json.Unmarshal(manifestRaw, &item.Manifest)
	return &item, nil
}

const ecosystemVersionSelect = `SELECT id,package_id,version,manifest_json,checksum,status,created_by,created_at FROM ecosystem_package_versions`

func (r *MySQL) CreateEcosystemPackageVersion(ctx context.Context, item model.EcosystemPackageVersion) (*model.EcosystemPackageVersion, error) {
	raw, _ := json.Marshal(item.Manifest)
	res, err := r.db.ExecContext(ctx, `INSERT INTO ecosystem_package_versions(package_id,version,manifest_json,checksum,status,created_by) VALUES(?,?,?,?,?,?)`, item.PackageID, item.Version, raw, item.Checksum, item.Status, item.CreatedBy)
	if err != nil {
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	return r.EcosystemPackageVersionByID(ctx, id)
}

func (r *MySQL) EcosystemPackageVersionByID(ctx context.Context, id int64) (*model.EcosystemPackageVersion, error) {
	return scanEcosystemVersion(r.db.QueryRowContext(ctx, ecosystemVersionSelect+` WHERE id=? LIMIT 1`, id))
}

func (r *MySQL) EcosystemPackageVersion(ctx context.Context, packageID int64, version string) (*model.EcosystemPackageVersion, error) {
	if strings.TrimSpace(version) == "" {
		return scanEcosystemVersion(r.db.QueryRowContext(ctx, ecosystemVersionSelect+` WHERE package_id=? AND status='VALIDATED' ORDER BY id DESC LIMIT 1`, packageID))
	}
	return scanEcosystemVersion(r.db.QueryRowContext(ctx, ecosystemVersionSelect+` WHERE package_id=? AND version=? LIMIT 1`, packageID, version))
}

func (r *MySQL) ListEcosystemPackageVersions(ctx context.Context, packageID int64) ([]model.EcosystemPackageVersion, error) {
	rows, err := r.db.QueryContext(ctx, ecosystemVersionSelect+` WHERE package_id=? ORDER BY id DESC`, packageID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.EcosystemPackageVersion{}
	for rows.Next() {
		item, err := scanEcosystemVersion(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *item)
	}
	return out, rows.Err()
}

func (r *MySQL) PublishEcosystemPackage(ctx context.Context, packageID int64, version string) error {
	_, err := r.db.ExecContext(ctx, `UPDATE ecosystem_packages SET status='PUBLISHED',visibility='PUBLIC',latest_version=?,updated_at=CURRENT_TIMESTAMP(6) WHERE id=?`, version, packageID)
	return err
}

func (r *MySQL) EcosystemOverview(ctx context.Context) (model.EcosystemOverview, error) {
	var out model.EcosystemOverview
	err := r.db.QueryRowContext(ctx, `
        SELECT
          COUNT(*),
          COALESCE(SUM(kind='AGENT'),0),
          COALESCE(SUM(kind='MCP'),0),
          COALESCE(SUM(kind='PLUGIN'),0),
          COALESCE(SUM(install_count),0)
        FROM ecosystem_packages WHERE status='PUBLISHED' AND visibility='PUBLIC'`).Scan(&out.PublishedPackages, &out.AgentPackages, &out.MCPPackages, &out.PluginPackages, &out.TotalInstalls)
	return out, err
}

func scanInstallation(s scanner) (*model.ProjectPackageInstallation, error) {
	var item model.ProjectPackageInstallation
	var configRaw []byte
	var resourceID sql.NullInt64
	if err := s.Scan(&item.ID, &item.ProjectID, &item.PackageID, &item.VersionID, &item.PackageSlug, &item.PackageName, &item.Kind, &item.Version, &item.Enabled, &configRaw, &item.ResourceType, &resourceID, &item.InstalledBy, &item.CreatedAt, &item.UpdatedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	item.Config = decodeMap(configRaw)
	if resourceID.Valid {
		item.ResourceID = &resourceID.Int64
	}
	return &item, nil
}

const installationSelect = `
SELECT i.id,i.project_id,i.package_id,i.version_id,p.slug,p.name,p.kind,v.version,i.enabled,i.config_json,i.resource_type,i.resource_id,i.installed_by,i.created_at,i.updated_at
FROM project_package_installations i
INNER JOIN ecosystem_packages p ON p.id=i.package_id
INNER JOIN ecosystem_package_versions v ON v.id=i.version_id`

func (r *MySQL) UpsertProjectPackageInstallation(ctx context.Context, item model.ProjectPackageInstallation) (*model.ProjectPackageInstallation, error) {
	configRaw, _ := json.Marshal(item.Config)
	_, err := r.db.ExecContext(ctx, `
        INSERT INTO project_package_installations(project_id,package_id,version_id,enabled,config_json,resource_type,resource_id,installed_by)
        VALUES(?,?,?,?,?,?,?,?)
        ON DUPLICATE KEY UPDATE version_id=VALUES(version_id),enabled=VALUES(enabled),config_json=VALUES(config_json),resource_type=VALUES(resource_type),resource_id=VALUES(resource_id),installed_by=VALUES(installed_by),updated_at=CURRENT_TIMESTAMP(6)`,
		item.ProjectID, item.PackageID, item.VersionID, item.Enabled, configRaw, item.ResourceType, item.ResourceID, item.InstalledBy)
	if err != nil {
		return nil, err
	}
	return r.ProjectPackageInstallationByPackage(ctx, item.ProjectID, item.PackageID)
}

func (r *MySQL) IncrementEcosystemPackageInstallCount(ctx context.Context, packageID int64) error {
	_, err := r.db.ExecContext(ctx, `UPDATE ecosystem_packages SET install_count=install_count+1 WHERE id=?`, packageID)
	return err
}

func (r *MySQL) ProjectPackageInstallationByPackage(ctx context.Context, projectID, packageID int64) (*model.ProjectPackageInstallation, error) {
	return scanInstallation(r.db.QueryRowContext(ctx, installationSelect+` WHERE i.project_id=? AND i.package_id=? LIMIT 1`, projectID, packageID))
}

func (r *MySQL) ListProjectPackageInstallations(ctx context.Context, projectID int64) ([]model.ProjectPackageInstallation, error) {
	rows, err := r.db.QueryContext(ctx, installationSelect+` WHERE i.project_id=? ORDER BY i.updated_at DESC,i.id DESC`, projectID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []model.ProjectPackageInstallation{}
	for rows.Next() {
		item, err := scanInstallation(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *item)
	}
	return out, rows.Err()
}

func (r *MySQL) ProjectPackageInstallationByID(ctx context.Context, projectID, id int64) (*model.ProjectPackageInstallation, error) {
	return scanInstallation(r.db.QueryRowContext(ctx, installationSelect+` WHERE i.project_id=? AND i.id=? LIMIT 1`, projectID, id))
}

func (r *MySQL) UpdateProjectPackageInstallationState(ctx context.Context, projectID, id int64, enabled bool, resourceType string, resourceID *int64) (*model.ProjectPackageInstallation, error) {
	res, err := r.db.ExecContext(ctx, `UPDATE project_package_installations SET enabled=?,resource_type=?,resource_id=?,updated_at=CURRENT_TIMESTAMP(6) WHERE project_id=? AND id=?`, enabled, resourceType, resourceID, projectID, id)
	if err != nil {
		return nil, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	return r.ProjectPackageInstallationByID(ctx, projectID, id)
}

func (r *MySQL) DeleteProjectPackageInstallation(ctx context.Context, projectID, id int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM project_package_installations WHERE project_id=? AND id=?`, projectID, id)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	return n > 0, err
}
