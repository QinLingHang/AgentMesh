package repository

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"

	"example.com/agentmesh-control-plane/internal/model"
)

// durableEventFingerprint includes the execution identity and fencing epoch.
// A recovered attempt must never collapse into a previous attempt's event.
func durableEventFingerprint(taskStatus, jobStatus, executionID string, fenceEpoch int64) string {
	hash := sha256.Sum256([]byte(fmt.Sprintf("%d:%s|%d:%s|%d:%s|%d", len(taskStatus), taskStatus,
		len(jobStatus), jobStatus, len(executionID), executionID, fenceEpoch)))
	return hex.EncodeToString(hash[:])
}

// workerPhaseFingerprint is stable for network retries of a single attempt.
// Its namespace cannot collide with the state snapshot fingerprint.
func workerPhaseFingerprint(executionID string, fenceEpoch, ordinal int64) string {
	hash := sha256.Sum256([]byte(fmt.Sprintf("worker-phase|%d:%s|%d|%d", len(executionID), executionID, fenceEpoch, ordinal)))
	return hex.EncodeToString(hash[:])
}

// AppendDurableWorkerPhase authenticates the exact current worker assignment
// and inserts under the same atomic statement. The worker cannot choose a task
// or forge a status; data is projected from the trusted job/task rows.
func (r *MySQL) AppendDurableWorkerPhase(ctx context.Context, jobID int64, executionID, workerID, leaseToken string, fenceEpoch, ordinal int64, phase, phaseStatus string) (bool, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return false, err
	}
	defer tx.Rollback()
	// Lock the authoritative attempt and its task before admitting an event.
	// A stale worker cannot race past a concurrent fence increment or cancel.
	var taskID int64
	var taskStatus, jobStatus string
	err = tx.QueryRowContext(ctx, `
		SELECT t.id, t.status, j.status
		FROM runtime_jobs j JOIN tasks t ON t.id=j.task_id
		WHERE j.id=? AND j.execution_id=? AND j.worker_id=? AND j.lease_token=?
		  AND j.fence_epoch=? AND j.status IN ('DISPATCHING','ACCEPTED')
		  AND j.lease_expires_at > UTC_TIMESTAMP(6)
		  AND t.status='RUNNING' AND t.delivery_mode='durable'
		FOR UPDATE
	`, jobID, executionID, workerID, leaseToken, fenceEpoch).Scan(&taskID, &taskStatus, &jobStatus)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	res, err := tx.ExecContext(ctx, `
		INSERT IGNORE INTO durable_task_events
		(task_id, state_hash, task_status, job_status, fence_epoch, event_type, phase, phase_status)
		VALUES (?, ?, ?, ?, ?, 'trace', ?, ?)
	`, taskID, workerPhaseFingerprint(executionID, fenceEpoch, ordinal), taskStatus, jobStatus, fenceEpoch, phase, phaseStatus)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	if err := tx.Commit(); err != nil {
		return false, err
	}
	return n == 1, nil
}

func appendDurableSnapshotTx(ctx context.Context, tx *sql.Tx, taskID int64, taskStatus, jobStatus, executionID string, fenceEpoch int64) error {
	_, err := tx.ExecContext(ctx, `
		INSERT IGNORE INTO durable_task_events
		(task_id, state_hash, task_status, job_status, fence_epoch)
		VALUES (?, ?, ?, ?, ?)
	`, taskID, durableEventFingerprint(taskStatus, jobStatus, executionID, fenceEpoch),
		taskStatus, jobStatus, fenceEpoch)
	return err
}

// SyncAndListDurableTaskEvents verifies ownership before reading either the job
// or its journal. A snapshot is persisted on subscription so a completion
// committed immediately before a gateway crash remains visible after restart.
// It deliberately contains no result text, prompts, worker endpoints or tokens.
func (r *MySQL) SyncAndListDurableTaskEvents(ctx context.Context, uid, taskID, after int64, limit int) ([]model.DurableTaskEvent, string, error) {
	if after < 0 || taskID <= 0 || uid <= 0 {
		return nil, "", ErrNotOwned
	}
	if limit <= 0 || limit > 100 {
		limit = 100
	}
	var taskStatus, jobStatus, executionID string
	var fenceEpoch int64
	err := r.db.QueryRowContext(ctx, `
		SELECT t.status, j.status, j.execution_id, j.fence_epoch
		FROM tasks t INNER JOIN runtime_jobs j ON j.task_id = t.id
		WHERE t.id = ? AND t.user_id = ? AND t.delivery_mode = 'durable'
	`, taskID, uid).Scan(&taskStatus, &jobStatus, &executionID, &fenceEpoch)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, "", ErrNotOwned
	}
	if err != nil {
		return nil, "", err
	}
	// Re-check the observed state in the INSERT's SELECT. A concurrent cancel,
	// completion or fence replacement cannot add a stale snapshot after it wins.
	_, err = r.db.ExecContext(ctx, `
		INSERT IGNORE INTO durable_task_events
		(task_id, state_hash, task_status, job_status, fence_epoch)
		SELECT t.id, ?, t.status, j.status, j.fence_epoch
		FROM tasks t INNER JOIN runtime_jobs j ON j.task_id=t.id
		WHERE t.id=? AND t.user_id=? AND t.delivery_mode='durable'
		  AND t.status=? AND j.status=? AND j.execution_id=? AND j.fence_epoch=?
	`, durableEventFingerprint(taskStatus, jobStatus, executionID, fenceEpoch),
		taskID, uid, taskStatus, jobStatus, executionID, fenceEpoch)
	if err != nil {
		return nil, "", err
	}

	rows, err := r.db.QueryContext(ctx, `
		SELECT sequence, task_id, task_status, job_status, fence_epoch, event_type, phase, phase_status, created_at
		FROM durable_task_events WHERE task_id=? AND sequence>?
		ORDER BY sequence ASC LIMIT ?
	`, taskID, after, limit)
	if err != nil {
		return nil, "", err
	}
	defer rows.Close()
	events := make([]model.DurableTaskEvent, 0, limit)
	for rows.Next() {
		var e model.DurableTaskEvent
		if err := rows.Scan(&e.Sequence, &e.TaskID, &e.Status, &e.JobStatus, &e.FenceEpoch,
			&e.EventType, &e.Phase, &e.PhaseStatus, &e.CreatedAt); err != nil {
			return nil, "", err
		}
		events = append(events, e)
	}
	if err := rows.Err(); err != nil {
		return nil, "", err
	}
	return events, taskStatus, nil
}
