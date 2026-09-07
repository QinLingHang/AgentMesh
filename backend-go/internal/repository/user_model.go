package repository

import (
	"context"
	"database/sql"
	"errors"

	"example.com/agentmesh-control-plane/internal/model"
)

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
