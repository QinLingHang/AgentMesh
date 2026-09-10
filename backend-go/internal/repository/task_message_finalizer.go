package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"

	"example.com/agentmesh-control-plane/internal/model"

	mysqlDriver "github.com/go-sql-driver/mysql"
)

const taskMessageFinalizeAttempts = 3

func isRetryableTaskMessageFinalizeError(err error) bool {
	var mysqlErr *mysqlDriver.MySQLError
	if !errors.As(err, &mysqlErr) {
		return false
	}
	return mysqlErr.Number == 1205 || mysqlErr.Number == 1213
}

func (r *MySQL) withTaskMessageTransaction(
	ctx context.Context,
	fn func(*sql.Tx) error,
) error {
	var lastErr error

	for attempt := 0; attempt < taskMessageFinalizeAttempts; attempt++ {
		tx, err := r.db.BeginTx(ctx, nil)
		if err != nil {
			return err
		}

		err = fn(tx)
		if err == nil {
			// Commit errors are intentionally not retried. A connection failure at
			// commit can be ambiguous, so blindly replaying the transaction could
			// duplicate durable effects.
			if commitErr := tx.Commit(); commitErr != nil {
				return commitErr
			}
			return nil
		}

		_ = tx.Rollback()
		lastErr = err
		if !isRetryableTaskMessageFinalizeError(err) || attempt == taskMessageFinalizeAttempts-1 {
			return err
		}

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(time.Duration(attempt+1) * 20 * time.Millisecond):
		}
	}

	return lastErr
}

func createAssistantMessageTx(
	ctx context.Context,
	tx *sql.Tx,
	write AssistantMessageWrite,
) (*model.Message, error) {
	var ownedID int64
	if err := tx.QueryRowContext(
		ctx,
		`
		SELECT id
		FROM conversations
		WHERE id = ?
		  AND user_id = ?
		LIMIT 1
		FOR UPDATE
		`,
		write.ConversationID,
		write.UserID,
	).Scan(&ownedID); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotOwned
		}
		return nil, err
	}

	// The conversation row lock serializes same-conversation finalization, so
	// completed request+role lookup provides final-answer idempotence without
	// suppressing legitimate INPUT_REQUIRED/AUTH_REQUIRED continuation turns or
	// requiring a risky schema migration on an already-live messages table.
	if write.RequestID != "" && write.Status == "COMPLETED" {
		existing, err := scanMessage(tx.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				conversation_id,
				role,
				content,
				status,
				request_id,
				metadata_json,
				created_at
			FROM messages
			WHERE conversation_id = ?
			  AND role = 'assistant'
			  AND status = 'COMPLETED'
			  AND request_id = ?
			ORDER BY id DESC
			LIMIT 1
			`,
			write.ConversationID,
			write.RequestID,
		))
		if err != nil {
			return nil, err
		}
		if existing != nil {
			return existing, nil
		}
	}

	var requestValue any
	if write.RequestID != "" {
		requestValue = write.RequestID
	}

	var metadataValue any
	if write.Metadata != nil {
		data, err := json.Marshal(write.Metadata)
		if err != nil {
			return nil, err
		}
		metadataValue = string(data)
	}

	res, err := tx.ExecContext(
		ctx,
		`
		INSERT INTO messages(
			conversation_id,
			role,
			content,
			status,
			request_id,
			metadata_json
		)
		VALUES(?, 'assistant', ?, ?, ?, ?)
		`,
		write.ConversationID,
		write.Content,
		write.Status,
		requestValue,
		metadataValue,
	)
	if err != nil {
		return nil, err
	}

	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}

	if _, err := tx.ExecContext(
		ctx,
		`
		UPDATE conversations
		SET
			last_message_at = CURRENT_TIMESTAMP(6),
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		write.ConversationID,
		write.UserID,
	); err != nil {
		return nil, err
	}

	return scanMessage(tx.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			conversation_id,
			role,
			content,
			status,
			request_id,
			metadata_json,
			created_at
		FROM messages
		WHERE id = ?
		`,
		id,
	))
}

func encodeTaskFinalizationPayloads(
	selected []string,
	trace []map[string]any,
	dag map[string]any,
) (string, string, string, error) {
	selectedJSON, err := json.Marshal(selected)
	if err != nil {
		return "", "", "", err
	}
	traceJSON, err := json.Marshal(trace)
	if err != nil {
		return "", "", "", err
	}
	dagJSON, err := json.Marshal(dag)
	if err != nil {
		return "", "", "", err
	}
	return string(selectedJSON), string(traceJSON), string(dagJSON), nil
}

func (r *MySQL) CompleteTaskWithAssistantMessage(
	ctx context.Context,
	task TaskCompletionWrite,
	message AssistantMessageWrite,
) (*model.Message, error) {
	if task.UserID != message.UserID || task.ConversationID != message.ConversationID {
		return nil, ErrNotOwned
	}

	selectedJSON, traceJSON, dagJSON, err := encodeTaskFinalizationPayloads(task.Selected, task.Trace, task.DAG)
	if err != nil {
		return nil, err
	}

	var persisted *model.Message
	err = r.withTaskMessageTransaction(ctx, func(tx *sql.Tx) error {
		res, err := tx.ExecContext(
			ctx,
			`
			UPDATE tasks
			SET
				status = 'COMPLETED',
				result_text = ?,
				selected_agents_json = ?,
				trace_json = ?,
				dag_json = ?,
				latency_ms = ?,
				estimated_cost = ?,
				error_message = NULL,
				continuation_json = NULL
			WHERE id = ?
			  AND user_id = ?
			  AND conversation_id = ?
			  AND status = 'RUNNING'
			`,
			task.Result,
			selectedJSON,
			traceJSON,
			dagJSON,
			task.LatencyMS,
			task.EstimatedCost,
			task.TaskID,
			task.UserID,
			task.ConversationID,
		)
		if err != nil {
			return err
		}
		affected, err := res.RowsAffected()
		if err != nil {
			return err
		}
		if affected != 1 {
			return ErrInvalidTaskState
		}

		persisted, err = createAssistantMessageTx(ctx, tx, message)
		return err
	})
	if err != nil {
		return nil, err
	}
	return persisted, nil
}

func (r *MySQL) SuspendTaskWithAssistantMessage(
	ctx context.Context,
	task TaskSuspensionWrite,
	message AssistantMessageWrite,
) (*model.Message, error) {
	if task.UserID != message.UserID || task.ConversationID != message.ConversationID {
		return nil, ErrNotOwned
	}
	if task.Continuation == nil {
		return nil, errors.New("continuation is required")
	}
	if task.Status != "INPUT_REQUIRED" && task.Status != "AUTH_REQUIRED" {
		return nil, ErrInvalidTaskState
	}

	continuationJSON, err := json.Marshal(task.Continuation)
	if err != nil {
		return nil, err
	}
	selectedJSON, traceJSON, dagJSON, err := encodeTaskFinalizationPayloads(task.Selected, task.Trace, task.DAG)
	if err != nil {
		return nil, err
	}

	var persisted *model.Message
	err = r.withTaskMessageTransaction(ctx, func(tx *sql.Tx) error {
		res, err := tx.ExecContext(
			ctx,
			`
			UPDATE tasks
			SET
				status = ?,
				result_text = ?,
				selected_agents_json = ?,
				trace_json = ?,
				dag_json = ?,
				latency_ms = ?,
				estimated_cost = ?,
				error_message = NULL,
				continuation_json = ?
			WHERE id = ?
			  AND user_id = ?
			  AND conversation_id = ?
			  AND status = 'RUNNING'
			`,
			task.Status,
			task.Result,
			selectedJSON,
			traceJSON,
			dagJSON,
			task.LatencyMS,
			task.EstimatedCost,
			string(continuationJSON),
			task.TaskID,
			task.UserID,
			task.ConversationID,
		)
		if err != nil {
			return err
		}
		affected, err := res.RowsAffected()
		if err != nil {
			return err
		}
		if affected != 1 {
			return ErrInvalidTaskState
		}

		persisted, err = createAssistantMessageTx(ctx, tx, message)
		return err
	})
	if err != nil {
		return nil, err
	}
	return persisted, nil
}
