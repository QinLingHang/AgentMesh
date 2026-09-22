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

// DirectSubmissionRepository commits the direct task, idempotency tombstone and
// user message together. A competing request never executes a second task.
// Existing legacy clients without a key continue using CreateTask.
type DirectSubmissionRepository interface {
	CreateDirectSubmission(context.Context, model.Task, model.TaskConstraints) (*model.Task, bool, error)
	LookupDurableSubmission(context.Context, int64, string) (*model.Task, string, error)
}

func (r *MySQL) CreateDirectSubmission(ctx context.Context, task model.Task, constraints model.TaskConstraints) (*model.Task, bool, error) {
	if task.ClientRequestID == "" || task.RequestFingerprint == "" {
		return nil, false, ErrSubmissionConflict
	}
	constraintsJSON, err := json.Marshal(constraints)
	if err != nil {
		return nil, false, err
	}
	modelJSON, err := json.Marshal(task.ModelSelection)
	if err != nil {
		return nil, false, err
	}
	ragJSON, err := json.Marshal(task.RagPolicy)
	if err != nil {
		return nil, false, err
	}
	effectiveJSON, err := json.Marshal(task.EffectiveRagPolicy)
	if err != nil {
		return nil, false, err
	}
	metaJSON, err := json.Marshal(task.PendingUserMessageMetadata)
	if err != nil {
		return nil, false, err
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()

	// Either the task's request_id uniqueness or the submission ledger can
	// reject a concurrent retry. Roll back our entire transaction BEFORE
	// reading the committed ledger; otherwise a duplicate request can leak a
	// raw MySQL 1062 to the caller instead of replaying the original task.
	// A different client key (or an old task without a ledger entry) fails
	// closed: request_id equality alone never authorizes replay.
	replayOnDuplicate := func(insertErr error) (*model.Task, bool, error) {
		var duplicate *mysqlDriver.MySQLError
		if !errors.As(insertErr, &duplicate) || duplicate.Number != 1062 {
			return nil, false, insertErr
		}
		if rollbackErr := tx.Rollback(); rollbackErr != nil && !errors.Is(rollbackErr, sql.ErrTxDone) {
			return nil, false, rollbackErr
		}
		original, fingerprint, lookupErr := r.LookupDurableSubmission(ctx, task.UserID, task.ClientRequestID)
		if lookupErr != nil {
			return nil, false, lookupErr
		}
		if original == nil || fingerprint != task.RequestFingerprint || original.DeliveryMode != "direct" {
			return nil, false, ErrSubmissionConflict
		}
		return original, true, nil
	}
	if task.ConversationID != nil {
		var owned int64
		if err = tx.QueryRowContext(ctx, `SELECT id FROM conversations WHERE id=? AND user_id=? FOR UPDATE`, *task.ConversationID, task.UserID).Scan(&owned); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return nil, false, ErrNotOwned
			}
			return nil, false, err
		}
	}
	res, err := tx.ExecContext(ctx, `
 INSERT INTO tasks(user_id,conversation_id,request_id,task_text,scheduler,planner,
 execution_mode,synthesis_mode,model_selection_json,rag_policy_json,
 effective_rag_policy_json,delivery_mode,constraints_json,status)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,'direct',?,'RUNNING')`,
		task.UserID, task.ConversationID, task.RequestID, task.TaskText, task.Scheduler, task.Planner,
		task.ExecutionMode, task.SynthesisMode, string(modelJSON), string(ragJSON), string(effectiveJSON), string(constraintsJSON))
	if err != nil {
		return replayOnDuplicate(err)
	}
	taskID, err := res.LastInsertId()
	if err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO task_submission_keys(user_id,client_request_id,request_fingerprint,task_id) VALUES(?,?,?,?)`, task.UserID, task.ClientRequestID, task.RequestFingerprint, taskID); err != nil {
		return replayOnDuplicate(err)
	}
	if task.ConversationID != nil {
		if _, err = tx.ExecContext(ctx, `INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,'user',?,'COMPLETED',?,?)`, *task.ConversationID, task.TaskText, task.RequestID, string(metaJSON)); err != nil {
			return nil, false, err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE conversations SET last_message_at=CURRENT_TIMESTAMP(6),updated_at=CURRENT_TIMESTAMP(6) WHERE id=? AND user_id=?`, *task.ConversationID, task.UserID); err != nil {
			return nil, false, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	// A browser disconnect may cancel ctx immediately after Commit. The row is
	// already durable; reading it with the canceled ctx would strand a RUNNING
	// task before the caller can start execution or mark the task as failed.
	lookupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	created, err := r.TaskByID(lookupCtx, task.UserID, taskID)
	return created, false, err
}
