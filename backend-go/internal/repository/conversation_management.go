package repository

import (
	"context"

	"example.com/agentmesh-control-plane/internal/model"
)

func (r *MySQL) UpdateConversationTitle(
	ctx context.Context,
	uid int64,
	conversationID int64,
	title string,
) (*model.Conversation, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE conversations
		SET
			title = ?,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		title,
		conversationID,
		uid,
	)

	if err != nil {
		return nil,
			err
	}

	affected, err :=
		result.RowsAffected()

	if err != nil {
		return nil,
			err
	}

	if affected == 0 {
		return nil,
			nil
	}

	return r.ConversationByID(
		ctx,
		uid,
		conversationID,
	)
}
