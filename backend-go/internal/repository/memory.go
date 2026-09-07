package repository

import (
	"context"
	"database/sql"
	"errors"

	"example.com/agentmesh-control-plane/internal/model"

	mysqlDriver "github.com/go-sql-driver/mysql"
)

var ErrMemoryKeyExists = errors.New(
	"memory key exists",
)

const memoryColumns = `
	id,
	user_id,
	category,
	memory_key,
	content,
	source_type,
	confidence,
	status,
	last_accessed_at,
	created_at,
	updated_at
`

func scanMemory(
	s scanner,
) (*model.UserMemory, error) {
	var memory model.UserMemory
	var lastAccessedAt sql.NullTime

	err := s.Scan(
		&memory.ID,
		&memory.UserID,
		&memory.Category,
		&memory.MemoryKey,
		&memory.Content,
		&memory.SourceType,
		&memory.Confidence,
		&memory.Status,
		&lastAccessedAt,
		&memory.CreatedAt,
		&memory.UpdatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, nil
	}

	if err != nil {
		return nil, err
	}

	if lastAccessedAt.Valid {
		value := lastAccessedAt.Time
		memory.LastAccessedAt = &value
	}

	return &memory, nil
}

func memoryDuplicateError(
	err error,
) error {
	var mysqlErr *mysqlDriver.MySQLError

	if errors.As(
		err,
		&mysqlErr,
	) && mysqlErr.Number == 1062 {
		return ErrMemoryKeyExists
	}

	return err
}

func (r *MySQL) CreateMemory(
	ctx context.Context,
	uid int64,
	memory model.UserMemory,
) (*model.UserMemory, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO user_memories(
			user_id,
			category,
			memory_key,
			content,
			source_type,
			confidence,
			status
		)
		VALUES(?, ?, ?, ?, ?, ?, ?)
		`,
		uid,
		memory.Category,
		memory.MemoryKey,
		memory.Content,
		memory.SourceType,
		memory.Confidence,
		memory.Status,
	)

	if err != nil {
		return nil, memoryDuplicateError(
			err,
		)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return nil, err
	}

	return r.MemoryByID(
		ctx,
		uid,
		id,
	)
}

func (r *MySQL) MemoryByID(
	ctx context.Context,
	uid int64,
	id int64,
) (*model.UserMemory, error) {
	return scanMemory(
		r.db.QueryRowContext(
			ctx,
			`SELECT `+memoryColumns+`
			 FROM user_memories
			 WHERE id = ?
			   AND user_id = ?
			 LIMIT 1`,
			id,
			uid,
		),
	)
}

func (r *MySQL) MemoryByKey(
	ctx context.Context,
	uid int64,
	memoryKey string,
) (*model.UserMemory, error) {
	return scanMemory(
		r.db.QueryRowContext(
			ctx,
			`SELECT `+memoryColumns+`
			 FROM user_memories
			 WHERE user_id = ?
			   AND memory_key = ?
			 LIMIT 1`,
			uid,
			memoryKey,
		),
	)
}

func (r *MySQL) ListMemories(
	ctx context.Context,
	uid int64,
	filter model.MemoryFilter,
) ([]model.UserMemory, error) {
	query := `SELECT ` + memoryColumns + `
		FROM user_memories
		WHERE user_id = ?`

	args := []any{
		uid,
	}

	if filter.Category != "" {
		query += ` AND category = ?`
		args = append(
			args,
			filter.Category,
		)
	}

	if filter.Status != "" {
		query += ` AND status = ?`
		args = append(
			args,
			filter.Status,
		)
	}

	if filter.Keyword != "" {
		query += ` AND (
			memory_key LIKE ?
			OR content LIKE ?
		)`

		like := "%" + filter.Keyword + "%"

		args = append(
			args,
			like,
			like,
		)
	}

	query += ` ORDER BY updated_at DESC, id DESC LIMIT ?`
	args = append(
		args,
		filter.Limit,
	)

	rows, err := r.db.QueryContext(
		ctx,
		query,
		args...,
	)

	if err != nil {
		return nil, err
	}

	defer rows.Close()

	memories := make(
		[]model.UserMemory,
		0,
	)

	for rows.Next() {
		memory, err := scanMemory(
			rows,
		)

		if err != nil {
			return nil, err
		}

		memories = append(
			memories,
			*memory,
		)
	}

	return memories, rows.Err()
}

func (r *MySQL) ListActiveMemories(
	ctx context.Context,
	uid int64,
	limit int,
) ([]model.UserMemory, error) {
	return r.ListMemories(
		ctx,
		uid,
		model.MemoryFilter{
			Status: "active",
			Limit:  limit,
		},
	)
}

func (r *MySQL) UpdateMemory(
	ctx context.Context,
	uid int64,
	id int64,
	memory model.UserMemory,
) (*model.UserMemory, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE user_memories
		SET category = ?,
			memory_key = ?,
			content = ?,
			source_type = ?,
			confidence = ?,
			status = ?
		WHERE id = ?
		  AND user_id = ?
		`,
		memory.Category,
		memory.MemoryKey,
		memory.Content,
		memory.SourceType,
		memory.Confidence,
		memory.Status,
		id,
		uid,
	)

	if err != nil {
		return nil, memoryDuplicateError(
			err,
		)
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return nil, err
	}

	if affected == 0 {
		// MySQL can report 0 for a no-op update, so distinguish a missing
		// resource from an unchanged resource while preserving ownership.
		existing, err := r.MemoryByID(
			ctx,
			uid,
			id,
		)

		if err != nil ||
			existing == nil {
			return existing, err
		}
	}

	return r.MemoryByID(
		ctx,
		uid,
		id,
	)
}

func (r *MySQL) DeleteMemory(
	ctx context.Context,
	uid int64,
	id int64,
) (bool, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM user_memories
		WHERE id = ?
		  AND user_id = ?
		`,
		id,
		uid,
	)

	if err != nil {
		return false, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected > 0, nil
}

func (r *MySQL) TouchMemoryAccess(
	ctx context.Context,
	uid int64,
	id int64,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		UPDATE user_memories
		SET last_accessed_at = UTC_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		id,
		uid,
	)

	return err
}
