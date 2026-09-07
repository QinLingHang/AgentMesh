package repository

import (
	"context"
	"database/sql"
	"errors"

	"example.com/agentmesh-control-plane/internal/model"
)

type attachmentScanner interface{ Scan(...any) error }

func scanConversationAttachment(scanner attachmentScanner) (*model.ConversationAttachment, error) {
	var item model.ConversationAttachment
	err := scanner.Scan(
		&item.ID,
		&item.UserID,
		&item.ConversationID,
		&item.OriginalName,
		&item.MediaType,
		&item.Extension,
		&item.SizeBytes,
		&item.ChecksumSHA256,
		&item.StorageKey,
		&item.CreatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}

const conversationAttachmentSelect = `
	SELECT id, user_id, conversation_id, original_name, media_type, extension,
	       size_bytes, checksum_sha256, storage_key, created_at
	FROM conversation_attachments
`

func (r *MySQL) CreateConversationAttachment(ctx context.Context, item model.ConversationAttachment) (*model.ConversationAttachment, error) {
	var owned int64
	if err := r.db.QueryRowContext(ctx, `SELECT id FROM conversations WHERE id=? AND user_id=? LIMIT 1`, item.ConversationID, item.UserID).Scan(&owned); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotOwned
		}
		return nil, err
	}
	res, err := r.db.ExecContext(ctx, `
		INSERT INTO conversation_attachments(
			user_id, conversation_id, original_name, media_type, extension,
			size_bytes, checksum_sha256, storage_key
		) VALUES(?,?,?,?,?,?,?,?)`,
		item.UserID, item.ConversationID, item.OriginalName, item.MediaType, item.Extension,
		item.SizeBytes, item.ChecksumSHA256, item.StorageKey,
	)
	if err != nil {
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	return r.ConversationAttachmentByID(ctx, item.UserID, item.ConversationID, id)
}

func (r *MySQL) ConversationAttachmentByID(ctx context.Context, uid, conversationID, attachmentID int64) (*model.ConversationAttachment, error) {
	return scanConversationAttachment(r.db.QueryRowContext(ctx, conversationAttachmentSelect+`
		WHERE id=? AND user_id=? AND conversation_id=? LIMIT 1`, attachmentID, uid, conversationID))
}

func (r *MySQL) ListConversationAttachments(ctx context.Context, uid, conversationID int64) ([]model.ConversationAttachment, error) {
	var owned int64
	if err := r.db.QueryRowContext(ctx, `SELECT id FROM conversations WHERE id=? AND user_id=? LIMIT 1`, conversationID, uid).Scan(&owned); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotOwned
		}
		return nil, err
	}
	rows, err := r.db.QueryContext(ctx, conversationAttachmentSelect+`
		WHERE user_id=? AND conversation_id=? ORDER BY id ASC`, uid, conversationID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []model.ConversationAttachment{}
	for rows.Next() {
		item, err := scanConversationAttachment(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *item)
	}
	return result, rows.Err()
}

func (r *MySQL) DeleteConversationAttachment(ctx context.Context, uid, conversationID, attachmentID int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM conversation_attachments WHERE id=? AND user_id=? AND conversation_id=?`, attachmentID, uid, conversationID)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	return n > 0, err
}
