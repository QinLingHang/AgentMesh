package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

const runtimeJobColumns = `
	id, task_id, user_id, request_id, execution_id, status, worker_id,
	attempt_count, max_attempts, deadline_at, lease_expires_at, accepted_at,
	last_error, created_at, updated_at
`

func scanRuntimeJob(s scanner) (*model.RuntimeJob, error) {
	var job model.RuntimeJob
	var workerID sql.NullString
	var leaseExpires sql.NullTime
	var acceptedAt sql.NullTime
	var lastError sql.NullString

	err := s.Scan(
		&job.ID, &job.TaskID, &job.UserID, &job.RequestID, &job.ExecutionID,
		&job.Status, &workerID, &job.AttemptCount, &job.MaxAttempts,
		&job.DeadlineAt, &leaseExpires, &acceptedAt, &lastError,
		&job.CreatedAt, &job.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if workerID.Valid {
		v := workerID.String
		job.WorkerID = &v
	}
	if leaseExpires.Valid {
		v := leaseExpires.Time
		job.LeaseExpiresAt = &v
	}
	if acceptedAt.Valid {
		v := acceptedAt.Time
		job.AcceptedAt = &v
	}
	if lastError.Valid {
		v := lastError.String
		job.LastError = &v
	}
	return &job, nil
}

func (r *MySQL) CreateQueuedTaskAndRuntimeJob(
	ctx context.Context,
	task model.Task,
	constraints model.TaskConstraints,
	requestJSON []byte,
	executionID string,
	deadline time.Time,
	maxAttempts int,
) (*model.Task, *model.RuntimeJob, error) {
	constraintsJSON, err := json.Marshal(constraints)
	if err != nil {
		return nil, nil, err
	}
	if maxAttempts < 1 {
		maxAttempts = 1
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()

	res, err := tx.ExecContext(ctx, `
		INSERT INTO tasks(
			user_id, conversation_id, request_id, task_text, scheduler, planner,
			execution_mode, synthesis_mode, delivery_mode, constraints_json, status
		) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'durable', ?, 'QUEUED')
	`, task.UserID, task.ConversationID, task.RequestID, task.TaskText,
		task.Scheduler, task.Planner, task.ExecutionMode, task.SynthesisMode,
		string(constraintsJSON))
	if err != nil {
		return nil, nil, err
	}
	taskID, err := res.LastInsertId()
	if err != nil {
		return nil, nil, err
	}

	jobRes, err := tx.ExecContext(ctx, `
		INSERT INTO runtime_jobs(
			task_id, user_id, request_id, execution_id, request_json, status,
			attempt_count, max_attempts, deadline_at, next_attempt_at
		) VALUES(?, ?, ?, ?, ?, 'QUEUED', 0, ?, ?, UTC_TIMESTAMP(6))
	`, taskID, task.UserID, task.RequestID, executionID, requestJSON,
		maxAttempts, deadline.UTC())
	if err != nil {
		return nil, nil, err
	}
	jobID, err := jobRes.LastInsertId()
	if err != nil {
		return nil, nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}

	createdTask, err := r.TaskByID(ctx, task.UserID, taskID)
	if err != nil {
		return nil, nil, err
	}
	job, err := r.RuntimeJobByID(ctx, jobID)
	if err != nil {
		return nil, nil, err
	}
	return createdTask, job, nil
}

func (r *MySQL) HeartbeatRuntimeWorker(ctx context.Context, worker model.RuntimeWorker) error {
	if worker.Capacity < 1 {
		worker.Capacity = 1
	}
	if worker.ActiveExecutions < 0 {
		worker.ActiveExecutions = 0
	}
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO runtime_workers(
			worker_id, endpoint, capacity, active_executions, draining, status,
			last_heartbeat_at
		) VALUES(?, ?, ?, ?, ?, 'ACTIVE', UTC_TIMESTAMP(6))
		ON DUPLICATE KEY UPDATE
			endpoint = VALUES(endpoint),
			capacity = VALUES(capacity),
			active_executions = VALUES(active_executions),
			draining = VALUES(draining),
			status = 'ACTIVE',
			last_heartbeat_at = UTC_TIMESTAMP(6)
	`, worker.WorkerID, worker.Endpoint, worker.Capacity,
		worker.ActiveExecutions, worker.Draining)
	return err
}

func scanRuntimeWorker(s scanner) (*model.RuntimeWorker, error) {
	var worker model.RuntimeWorker
	var circuit sql.NullTime
	err := s.Scan(
		&worker.WorkerID, &worker.Endpoint, &worker.Capacity,
		&worker.ActiveExecutions, &worker.Draining, &worker.Status,
		&worker.ConsecutiveFailures, &circuit, &worker.LastHeartbeatAt,
		&worker.CreatedAt, &worker.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if circuit.Valid {
		v := circuit.Time
		worker.CircuitOpenUntil = &v
	}
	return &worker, nil
}

func (r *MySQL) RuntimeWorkerByID(ctx context.Context, workerID string) (*model.RuntimeWorker, error) {
	return scanRuntimeWorker(r.db.QueryRowContext(ctx, `
		SELECT worker_id, endpoint, capacity, active_executions, draining, status,
			consecutive_failures, circuit_open_until, last_heartbeat_at, created_at, updated_at
		FROM runtime_workers WHERE worker_id = ? LIMIT 1
	`, workerID))
}

func (r *MySQL) ListAvailableRuntimeWorkers(ctx context.Context, staleBefore time.Time, limit int) ([]model.RuntimeWorker, error) {
	if limit <= 0 {
		limit = 32
	}
	rows, err := r.db.QueryContext(ctx, `
		SELECT worker_id, endpoint, capacity, active_executions, draining, status,
			consecutive_failures, circuit_open_until, last_heartbeat_at,
			created_at, updated_at
		FROM runtime_workers
		WHERE status = 'ACTIVE'
		  AND draining = 0
		  AND last_heartbeat_at >= ?
		  AND active_executions < capacity
		  AND (circuit_open_until IS NULL OR circuit_open_until <= UTC_TIMESTAMP(6))
		ORDER BY (active_executions / GREATEST(capacity, 1)) ASC,
			last_heartbeat_at DESC, worker_id ASC
		LIMIT ?
	`, staleBefore.UTC(), limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	workers := []model.RuntimeWorker{}
	for rows.Next() {
		worker, err := scanRuntimeWorker(rows)
		if err != nil {
			return nil, err
		}
		workers = append(workers, *worker)
	}
	return workers, rows.Err()
}

func (r *MySQL) ClaimNextRuntimeJob(
	ctx context.Context,
	workerID string,
	leaseToken string,
	leaseDuration time.Duration,
) (*model.RuntimeJob, []byte, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()

	// Serialize capacity reservations per worker. Heartbeat active counts are
	// telemetry; durable job states are authoritative for dispatch capacity.
	// Locking the worker row prevents multiple control-plane dispatchers from
	// over-claiming the same worker concurrently.
	var capacity int
	err = tx.QueryRowContext(ctx, `
		SELECT capacity FROM runtime_workers
		WHERE worker_id = ? AND status = 'ACTIVE' AND draining = 0
		FOR UPDATE
	`, workerID).Scan(&capacity)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	var active int
	if err = tx.QueryRowContext(ctx, `
		SELECT COUNT(*) FROM runtime_jobs
		WHERE worker_id = ? AND status IN ('LEASED','DISPATCHING','ACCEPTED','COMPLETING')
	`, workerID).Scan(&active); err != nil {
		return nil, nil, err
	}
	if active >= capacity {
		return nil, nil, nil
	}

	var jobID int64
	var taskID int64
	var requestJSON []byte
	err = tx.QueryRowContext(ctx, `
		SELECT id, task_id, request_json
		FROM runtime_jobs
		WHERE status = 'QUEUED'
		  AND next_attempt_at <= UTC_TIMESTAMP(6)
		  AND deadline_at > UTC_TIMESTAMP(6)
		  AND attempt_count < max_attempts
		ORDER BY id ASC
		LIMIT 1
		FOR UPDATE SKIP LOCKED
	`).Scan(&jobID, &taskID, &requestJSON)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}

	leaseExpires := time.Now().UTC().Add(leaseDuration)
	res, err := tx.ExecContext(ctx, `
		UPDATE runtime_jobs
		SET status = 'LEASED', worker_id = ?, lease_token = ?,
			lease_expires_at = ?, attempt_count = attempt_count + 1,
			last_error = NULL
		WHERE id = ? AND status = 'QUEUED'
	`, workerID, leaseToken, leaseExpires, jobID)
	if err != nil {
		return nil, nil, err
	}
	affected, _ := res.RowsAffected()
	if affected != 1 {
		return nil, nil, ErrInvalidTaskState
	}

	res, err = tx.ExecContext(ctx, `
		UPDATE tasks SET status = 'RUNNING', error_message = NULL
		WHERE id = ? AND status = 'QUEUED'
	`, taskID)
	if err != nil {
		return nil, nil, err
	}
	affected, _ = res.RowsAffected()
	if affected != 1 {
		return nil, nil, ErrInvalidTaskState
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	job, err := r.RuntimeJobByID(ctx, jobID)
	return job, requestJSON, err
}

func (r *MySQL) MarkRuntimeJobDispatching(ctx context.Context, jobID int64, workerID, leaseToken string) (bool, error) {
	res, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'DISPATCHING'
		WHERE id = ? AND status = 'LEASED' AND worker_id = ? AND lease_token = ?
	`, jobID, workerID, leaseToken)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	return affected == 1, err
}

func (r *MySQL) MarkRuntimeJobAccepted(ctx context.Context, jobID int64, workerID, leaseToken string) (bool, error) {
	res, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs
		SET status = 'ACCEPTED', accepted_at = COALESCE(accepted_at, UTC_TIMESTAMP(6)), lease_expires_at = NULL
		WHERE id = ? AND status = 'DISPATCHING' AND worker_id = ? AND lease_token = ?
	`, jobID, workerID, leaseToken)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	return affected == 1, err
}

func (r *MySQL) RuntimeJobByID(ctx context.Context, id int64) (*model.RuntimeJob, error) {
	return scanRuntimeJob(r.db.QueryRowContext(ctx, `SELECT `+runtimeJobColumns+` FROM runtime_jobs WHERE id = ? LIMIT 1`, id))
}

func (r *MySQL) BeginRuntimeJobCallback(ctx context.Context, jobID int64, executionID, workerID, leaseToken string) (bool, error) {
	res, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'COMPLETING'
		WHERE id = ? AND status IN ('DISPATCHING','ACCEPTED') AND execution_id = ?
		  AND worker_id = ? AND lease_token = ?
	`, jobID, executionID, workerID, leaseToken)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	return affected == 1, err
}

func (r *MySQL) MarkRuntimeJobCompleted(ctx context.Context, jobID int64) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'COMPLETED', lease_token = NULL,
			lease_expires_at = NULL, last_error = NULL
		WHERE id = ? AND status = 'COMPLETING'
	`, jobID)
	return err
}

func (r *MySQL) RequeueRuntimeJob(ctx context.Context, jobID int64, delay time.Duration, message string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	var taskID int64
	err = tx.QueryRowContext(ctx, `SELECT task_id FROM runtime_jobs WHERE id = ? AND status IN ('LEASED','DISPATCHING') FOR UPDATE`, jobID).Scan(&taskID)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'QUEUED', worker_id = NULL,
			lease_token = NULL, lease_expires_at = NULL,
			next_attempt_at = ?, last_error = ?
		WHERE id = ? AND status IN ('LEASED','DISPATCHING')
	`, time.Now().UTC().Add(delay), message, jobID)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `UPDATE tasks SET status = 'QUEUED' WHERE id = ? AND status = 'RUNNING'`, taskID)
	if err != nil {
		return err
	}
	return tx.Commit()
}

func (r *MySQL) FailRuntimeJob(ctx context.Context, jobID int64, message string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	var taskID int64
	err = tx.QueryRowContext(ctx, `SELECT task_id FROM runtime_jobs WHERE id = ? FOR UPDATE`, jobID).Scan(&taskID)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'FAILED', last_error = ?, lease_token = NULL,
			lease_expires_at = NULL
		WHERE id = ? AND status NOT IN ('COMPLETED','FAILED','CANCELED')
	`, message, jobID)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `
		UPDATE tasks SET status = 'ERROR', error_message = ?, continuation_json = NULL
		WHERE id = ? AND status IN ('QUEUED','RUNNING')
	`, message, taskID)
	if err != nil {
		return err
	}
	return tx.Commit()
}

func (r *MySQL) CancelRuntimeTask(ctx context.Context, uid, taskID int64) (*model.RuntimeJob, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var jobID int64
	err = tx.QueryRowContext(ctx, `
		SELECT rj.id FROM runtime_jobs rj
		INNER JOIN tasks t ON t.id = rj.task_id
		WHERE rj.task_id = ? AND t.user_id = ? LIMIT 1 FOR UPDATE
	`, taskID, uid).Scan(&jobID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotOwned
	}
	if err != nil {
		return nil, err
	}
	res, err := tx.ExecContext(ctx, `
		UPDATE tasks SET status = 'CANCELED', continuation_json = NULL
		WHERE id = ? AND user_id = ? AND status IN ('QUEUED','RUNNING')
	`, taskID, uid)
	if err != nil {
		return nil, err
	}
	affected, _ := res.RowsAffected()
	if affected != 1 {
		return nil, ErrInvalidTaskState
	}
	_, err = tx.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'CANCELED', lease_expires_at = NULL,
			last_error = 'canceled_by_user'
		WHERE id = ? AND status NOT IN ('COMPLETED','FAILED','CANCELED')
	`, jobID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return r.RuntimeJobByID(ctx, jobID)
}

func (r *MySQL) RecoverExpiredRuntimeLeases(ctx context.Context, now time.Time) (int64, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()

	rows, err := tx.QueryContext(ctx, `
		SELECT id, task_id FROM runtime_jobs
		WHERE status = 'LEASED' AND lease_expires_at < ? FOR UPDATE
	`, now.UTC())
	if err != nil {
		return 0, err
	}
	type pair struct{ jobID, taskID int64 }
	pairs := []pair{}
	for rows.Next() {
		var p pair
		if err := rows.Scan(&p.jobID, &p.taskID); err != nil {
			_ = rows.Close()
			return 0, err
		}
		pairs = append(pairs, p)
	}
	if err := rows.Close(); err != nil {
		return 0, err
	}

	for _, p := range pairs {
		if _, err = tx.ExecContext(ctx, `
			UPDATE runtime_jobs SET status='QUEUED', worker_id=NULL, lease_token=NULL,
				lease_expires_at=NULL, next_attempt_at=UTC_TIMESTAMP(6),
				last_error='lease_expired_before_acceptance'
			WHERE id=? AND status='LEASED'
		`, p.jobID); err != nil {
			return 0, err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE tasks SET status='QUEUED' WHERE id=? AND status='RUNNING'`, p.taskID); err != nil {
			return 0, err
		}
	}
	if err = tx.Commit(); err != nil {
		return 0, err
	}
	return int64(len(pairs)), nil
}

func (r *MySQL) ListExpiredAcceptedRuntimeJobs(ctx context.Context, now time.Time, limit int) ([]model.RuntimeJob, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := r.db.QueryContext(ctx, `
		SELECT `+runtimeJobColumns+` FROM runtime_jobs
		WHERE ((status IN ('DISPATCHING','ACCEPTED') AND deadline_at < ?)
		   OR (status = 'COMPLETING' AND updated_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 30 SECOND)))
		ORDER BY id ASC LIMIT ?
	`, now.UTC(), limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	jobs := []model.RuntimeJob{}
	for rows.Next() {
		job, err := scanRuntimeJob(rows)
		if err != nil {
			return nil, err
		}
		jobs = append(jobs, *job)
	}
	return jobs, rows.Err()
}

func (r *MySQL) RecordRuntimeWorkerDispatchSuccess(ctx context.Context, workerID string) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE runtime_workers SET consecutive_failures=0, circuit_open_until=NULL
		WHERE worker_id=?
	`, workerID)
	return err
}

func (r *MySQL) RecordRuntimeWorkerDispatchFailure(ctx context.Context, workerID string, threshold int, openFor time.Duration) error {
	if threshold < 1 {
		threshold = 1
	}
	_, err := r.db.ExecContext(ctx, `
		UPDATE runtime_workers
		SET consecutive_failures = consecutive_failures + 1,
			circuit_open_until = CASE
				WHEN consecutive_failures + 1 >= ? THEN ?
				ELSE circuit_open_until END
		WHERE worker_id = ?
	`, threshold, time.Now().UTC().Add(openFor), workerID)
	return err
}

func (r *MySQL) RuntimeReliabilitySnapshot(ctx context.Context, staleBefore time.Time) (*model.RuntimeReliabilitySnapshot, error) {
	snapshot := &model.RuntimeReliabilitySnapshot{Enabled: true}
	rows, err := r.db.QueryContext(ctx, `SELECT status, COUNT(*) FROM runtime_jobs GROUP BY status`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var status string
		var count int
		if err := rows.Scan(&status, &count); err != nil {
			_ = rows.Close()
			return nil, err
		}
		switch status {
		case "QUEUED":
			snapshot.QueueDepth = count
		case "LEASED":
			snapshot.Leased = count
		case "ACCEPTED", "COMPLETING":
			snapshot.Accepted += count
		case "FAILED":
			snapshot.Failed = count
		case "CANCELED":
			snapshot.Canceled = count
		}
	}
	_ = rows.Close()

	row := r.db.QueryRowContext(ctx, `
		SELECT COUNT(*),
			COALESCE(SUM(CASE WHEN status='ACTIVE' AND draining=0 AND last_heartbeat_at>=?
				AND active_executions<capacity AND (circuit_open_until IS NULL OR circuit_open_until<=UTC_TIMESTAMP(6)) THEN 1 ELSE 0 END),0),
			COALESCE(SUM(CASE WHEN draining=1 THEN 1 ELSE 0 END),0),
			COALESCE(SUM(CASE WHEN circuit_open_until>UTC_TIMESTAMP(6) THEN 1 ELSE 0 END),0)
		FROM runtime_workers
	`, staleBefore.UTC())
	if err := row.Scan(&snapshot.Workers, &snapshot.AvailableWorkers, &snapshot.DrainingWorkers, &snapshot.CircuitOpenWorkers); err != nil {
		return nil, err
	}
	var oldest sql.NullTime
	if err := r.db.QueryRowContext(ctx, `SELECT MIN(created_at) FROM runtime_jobs WHERE status='QUEUED'`).Scan(&oldest); err != nil {
		return nil, err
	}
	if oldest.Valid {
		snapshot.OldestQueuedMS = time.Since(oldest.Time).Milliseconds()
		if snapshot.OldestQueuedMS < 0 {
			snapshot.OldestQueuedMS = 0
		}
	}
	return snapshot, nil
}
