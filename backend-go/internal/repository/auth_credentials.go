package repository

import (
	"context"
	"errors"
)

var ErrCredentialUserNotFound = errors.New(
	"credential user not found",
)

// CredentialRepository contains security-sensitive account mutations that
// should remain transactional and separate from the normal UserRepository.
type CredentialRepository interface {
	ResetPasswordAndRevokeSessions(
		context.Context,
		int64,
		string,
	) error
}

// ResetPasswordAndRevokeSessions changes the password and revokes every
// outstanding refresh token in the same database transaction.
//
// After a password reset, all existing browser sessions therefore lose
// their ability to refresh access tokens.
func (r *MySQL) ResetPasswordAndRevokeSessions(
	ctx context.Context,
	userID int64,
	passwordHash string,
) error {
	tx, err := r.db.BeginTx(
		ctx,
		nil,
	)

	if err != nil {
		return err
	}

	defer func() {
		_ = tx.Rollback()
	}()

	result, err := tx.ExecContext(
		ctx,
		`
		UPDATE users
		SET
			password_hash = ?,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND status = 'ACTIVE'
		`,
		passwordHash,
		userID,
	)

	if err != nil {
		return err
	}

	affected, err := result.RowsAffected()

	if err != nil {
		return err
	}

	if affected != 1 {
		return ErrCredentialUserNotFound
	}

	if _, err = tx.ExecContext(
		ctx,
		`
		UPDATE refresh_tokens
		SET revoked_at = UTC_TIMESTAMP(6)
		WHERE user_id = ?
		  AND revoked_at IS NULL
		`,
		userID,
	); err != nil {
		return err
	}

	if err = tx.Commit(); err != nil {
		return err
	}

	return nil
}

var _ CredentialRepository = (*MySQL)(nil)
