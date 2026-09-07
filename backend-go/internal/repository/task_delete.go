package repository

import "context"

// DeleteTask removes only terminal task-history records.
//
// Conversation messages are intentionally NOT deleted here.
// They belong to the conversation history and have a separate lifecycle.
//
// Defense in depth:
// even if Service validation is bypassed, active / suspended tasks
// still cannot be deleted by this SQL statement.
func (r *MySQL) DeleteTask(
	ctx context.Context,
	uid int64,
	id int64,
) (bool, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM tasks
		WHERE id = ?
		  AND user_id = ?
		  AND status IN (
				'COMPLETED',
				'ERROR',
				'CANCELED'
		  )
		`,
		id,
		uid,
	)

	if err != nil {
		return false,
			err
	}

	affected, err :=
		result.RowsAffected()

	if err != nil {
		return false,
			err
	}

	return affected == 1,
		nil
}
