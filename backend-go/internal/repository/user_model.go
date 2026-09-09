package repository

import (
	"context"
	"database/sql"
	"errors"

	"example.com/agentmesh-control-plane/internal/model"
)

// -----------------------------------------------------------------------------
// Legacy single-provider storage
// -----------------------------------------------------------------------------

func (r *MySQL) GetUserModelProvider(ctx context.Context, uid int64) (*model.UserModelProvider, error) {
	var item model.UserModelProvider
	err := r.db.QueryRowContext(ctx, `SELECT user_id,provider,base_url,model_name,vision_model_name,masked_hint,enabled,created_at,updated_at FROM user_model_providers WHERE user_id=?`, uid).Scan(
		&item.UserID,
		&item.Provider,
		&item.BaseURL,
		&item.ModelName,
		&item.VisionModelName,
		&item.MaskedHint,
		&item.Enabled,
		&item.CreatedAt,
		&item.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}

func (r *MySQL) UserModelProviderCiphertext(ctx context.Context, uid int64) ([]byte, []byte, error) {
	var ciphertext []byte
	var nonce []byte
	err := r.db.QueryRowContext(ctx, `SELECT ciphertext,nonce FROM user_model_providers WHERE user_id=?`, uid).Scan(&ciphertext, &nonce)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, nil
	}
	return ciphertext, nonce, err
}

func (r *MySQL) UpsertUserModelProvider(ctx context.Context, item model.UserModelProvider, ciphertext, nonce []byte) (*model.UserModelProvider, error) {
	_, err := r.db.ExecContext(ctx, `INSERT INTO user_model_providers(user_id,provider,base_url,model_name,vision_model_name,ciphertext,nonce,masked_hint,enabled) VALUES(?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE provider=VALUES(provider),base_url=VALUES(base_url),model_name=VALUES(model_name),vision_model_name=VALUES(vision_model_name),ciphertext=VALUES(ciphertext),nonce=VALUES(nonce),masked_hint=VALUES(masked_hint),enabled=VALUES(enabled),updated_at=CURRENT_TIMESTAMP(6)`,
		item.UserID,
		item.Provider,
		item.BaseURL,
		item.ModelName,
		item.VisionModelName,
		ciphertext,
		nonce,
		item.MaskedHint,
		item.Enabled,
	)
	if err != nil {
		return nil, err
	}
	return r.GetUserModelProvider(ctx, item.UserID)
}

func (r *MySQL) DeleteUserModelProvider(ctx context.Context, uid int64) (bool, error) {
	result, err := r.db.ExecContext(ctx, `DELETE FROM user_model_providers WHERE user_id=?`, uid)
	if err != nil {
		return false, err
	}
	rows, err := result.RowsAffected()
	return rows > 0, err
}

// -----------------------------------------------------------------------------
// Multi-service model pool
// -----------------------------------------------------------------------------

type userModelServiceScanner interface {
	Scan(dest ...any) error
}

func scanUserModelService(scanner userModelServiceScanner) (*model.UserModelService, error) {
	var item model.UserModelService
	err := scanner.Scan(
		&item.ID,
		&item.ServiceKey,
		&item.UserID,
		&item.Name,
		&item.Provider,
		&item.BaseURL,
		&item.ModelName,
		&item.VisionModelName,
		&item.MaskedHint,
		&item.Enabled,
		&item.AutoRoute,
		&item.IsDefault,
		&item.CreatedAt,
		&item.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}

const userModelServiceColumns = `
	id,
	service_key,
	user_id,
	name,
	provider,
	base_url,
	model_name,
	vision_model_name,
	masked_hint,
	enabled,
	auto_route,
	is_default,
	created_at,
	updated_at
`

func (r *MySQL) ListUserModelServices(ctx context.Context, uid int64) ([]model.UserModelService, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT `+userModelServiceColumns+` FROM user_model_services WHERE user_id=? ORDER BY is_default DESC, id ASC`, uid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := []model.UserModelService{}
	for rows.Next() {
		item, err := scanUserModelService(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, *item)
	}
	return items, rows.Err()
}

func (r *MySQL) UserModelServiceByID(ctx context.Context, uid, id int64) (*model.UserModelService, error) {
	return scanUserModelService(r.db.QueryRowContext(ctx, `SELECT `+userModelServiceColumns+` FROM user_model_services WHERE id=? AND user_id=? LIMIT 1`, id, uid))
}

func (r *MySQL) UserModelServiceCiphertext(ctx context.Context, uid, id int64) ([]byte, []byte, error) {
	var ciphertext []byte
	var nonce []byte
	err := r.db.QueryRowContext(ctx, `SELECT ciphertext,nonce FROM user_model_services WHERE id=? AND user_id=?`, id, uid).Scan(&ciphertext, &nonce)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, nil
	}
	return ciphertext, nonce, err
}

func (r *MySQL) CreateUserModelService(ctx context.Context, item model.UserModelService, ciphertext, nonce []byte) (*model.UserModelService, error) {
	res, err := r.db.ExecContext(ctx, `INSERT INTO user_model_services(service_key,user_id,name,provider,base_url,model_name,vision_model_name,ciphertext,nonce,masked_hint,enabled,auto_route,is_default) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`,
		item.ServiceKey,
		item.UserID,
		item.Name,
		item.Provider,
		item.BaseURL,
		item.ModelName,
		item.VisionModelName,
		ciphertext,
		nonce,
		item.MaskedHint,
		item.Enabled,
		item.AutoRoute,
		item.IsDefault,
	)
	if err != nil {
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	return r.UserModelServiceByID(ctx, item.UserID, id)
}

func (r *MySQL) UpdateUserModelService(ctx context.Context, item model.UserModelService, ciphertext, nonce []byte) (*model.UserModelService, error) {
	result, err := r.db.ExecContext(ctx, `UPDATE user_model_services SET name=?,provider=?,base_url=?,model_name=?,vision_model_name=?,ciphertext=?,nonce=?,masked_hint=?,enabled=?,auto_route=?,is_default=?,updated_at=CURRENT_TIMESTAMP(6) WHERE id=? AND user_id=?`,
		item.Name,
		item.Provider,
		item.BaseURL,
		item.ModelName,
		item.VisionModelName,
		ciphertext,
		nonce,
		item.MaskedHint,
		item.Enabled,
		item.AutoRoute,
		item.IsDefault,
		item.ID,
		item.UserID,
	)
	if err != nil {
		return nil, err
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return nil, err
	}
	if rows == 0 {
		return nil, nil
	}
	return r.UserModelServiceByID(ctx, item.UserID, item.ID)
}

func (r *MySQL) DeleteUserModelService(ctx context.Context, uid, id int64) (bool, error) {
	result, err := r.db.ExecContext(ctx, `DELETE FROM user_model_services WHERE id=? AND user_id=?`, id, uid)
	if err != nil {
		return false, err
	}
	rows, err := result.RowsAffected()
	return rows > 0, err
}

func (r *MySQL) ClearUserModelDefault(ctx context.Context, uid int64, exceptID int64) error {
	if exceptID > 0 {
		_, err := r.db.ExecContext(ctx, `UPDATE user_model_services SET is_default=0 WHERE user_id=? AND id<>?`, uid, exceptID)
		return err
	}
	_, err := r.db.ExecContext(ctx, `UPDATE user_model_services SET is_default=0 WHERE user_id=?`, uid)
	return err
}

func (r *MySQL) SetFirstUserModelServiceDefault(ctx context.Context, uid int64) error {
	_, err := r.db.ExecContext(ctx, `UPDATE user_model_services SET is_default=1 WHERE id=(SELECT chosen.id FROM (SELECT id FROM user_model_services WHERE user_id=? AND enabled=1 ORDER BY id ASC LIMIT 1) chosen)`, uid)
	return err
}

func (r *MySQL) DeleteAllUserModelServices(ctx context.Context, uid int64) (int64, error) {
	result, err := r.db.ExecContext(ctx, `DELETE FROM user_model_services WHERE user_id=?`, uid)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}
