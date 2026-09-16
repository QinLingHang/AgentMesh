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
	id, task_id, user_id, request_id, execution_id, status, worker_id, node_id,
	fence_epoch, attempt_count, max_attempts, failover_retry_safe,
	deadline_at, lease_expires_at, accepted_at, last_error, created_at, updated_at
`

func scanRuntimeJob(s scanner) (*model.RuntimeJob, error) {
	var job model.RuntimeJob
	var workerID sql.NullString
	var nodeID sql.NullString
	var leaseExpires sql.NullTime
	var acceptedAt sql.NullTime
	var lastError sql.NullString

	err := s.Scan(
		&job.ID, &job.TaskID, &job.UserID, &job.RequestID, &job.ExecutionID,
		&job.Status, &workerID, &nodeID, &job.FenceEpoch, &job.AttemptCount,
		&job.MaxAttempts, &job.FailoverRetrySafe, &job.DeadlineAt,
		&leaseExpires, &acceptedAt, &lastError, &job.CreatedAt, &job.UpdatedAt,
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
	if nodeID.Valid {
		v := nodeID.String
		job.NodeID = &v
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
	modelSelectionJSON, err := json.Marshal(task.ModelSelection)
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
			execution_mode, synthesis_mode, model_selection_json, delivery_mode, constraints_json, status
		) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'durable', ?, 'QUEUED')
	`, task.UserID, task.ConversationID, task.RequestID, task.TaskText,
		task.Scheduler, task.Planner, task.ExecutionMode, task.SynthesisMode,
		string(modelSelectionJSON), string(constraintsJSON))
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
			attempt_count, max_attempts, failover_retry_safe, deadline_at, next_attempt_at
		) VALUES(?, ?, ?, ?, ?, 'QUEUED', 0, ?, ?, ?, UTC_TIMESTAMP(6))
	`, taskID, task.UserID, task.RequestID, executionID, requestJSON,
		maxAttempts, constraints.RetryOnWorkerLoss, deadline.UTC())
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
	if worker.NodeID == "" {
		worker.NodeID = worker.WorkerID
	}
	if worker.NodeCapacity < 1 {
		worker.NodeCapacity = worker.Capacity
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()

	_, err = tx.ExecContext(ctx, `
		INSERT INTO runtime_workers(
			worker_id, node_id, zone, version, started_at, endpoint, capacity,
			active_executions, draining, status, last_heartbeat_at
		) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', UTC_TIMESTAMP(6))
		ON DUPLICATE KEY UPDATE
			node_id = VALUES(node_id),
			zone = VALUES(zone),
			version = VALUES(version),
			started_at = COALESCE(runtime_workers.started_at, VALUES(started_at)),
			endpoint = VALUES(endpoint),
			capacity = VALUES(capacity),
			active_executions = VALUES(active_executions),
			draining = VALUES(draining),
			status = 'ACTIVE',
			last_heartbeat_at = UTC_TIMESTAMP(6)
	`, worker.WorkerID, worker.NodeID, worker.Zone, worker.Version, worker.StartedAt,
		worker.Endpoint, worker.Capacity, worker.ActiveExecutions, worker.Draining)
	if err != nil {
		return err
	}

	_, err = tx.ExecContext(ctx, `
		INSERT INTO runtime_nodes(
			node_id, zone, version, capacity, declared_capacity, active_executions, worker_count,
			draining, status, last_heartbeat_at
		) VALUES(?, ?, ?, ?, ?, ?, 1, ?, 'ACTIVE', UTC_TIMESTAMP(6))
		ON DUPLICATE KEY UPDATE
			zone = VALUES(zone),
			version = VALUES(version),
			declared_capacity = VALUES(declared_capacity),
			draining = VALUES(draining),
			status = 'ACTIVE',
			last_heartbeat_at = UTC_TIMESTAMP(6)
	`, worker.NodeID, worker.Zone, worker.Version, worker.NodeCapacity, worker.NodeCapacity,
		worker.ActiveExecutions, worker.Draining)
	if err != nil {
		return err
	}

	// Aggregate the current worker view into the node row so multiple Runtime
	// worker processes on one machine are capacity-aware rather than racing on
	// independent heartbeat counters.
	_, err = tx.ExecContext(ctx, `
		UPDATE runtime_nodes n
		SET n.capacity = LEAST(
				GREATEST(n.declared_capacity, 1),
				GREATEST(COALESCE((
					SELECT SUM(w.capacity) FROM runtime_workers w
					WHERE w.node_id = ? AND w.status = 'ACTIVE'
				), 0), 1)
			),
			n.active_executions = COALESCE((
				SELECT COUNT(*) FROM runtime_jobs j
				WHERE j.node_id = ? AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')
			), 0),
			n.worker_count = COALESCE((
				SELECT COUNT(*) FROM runtime_workers w
				WHERE w.node_id = ? AND w.status = 'ACTIVE'
			), 0),
			n.draining = CASE WHEN EXISTS(
				SELECT 1 FROM runtime_workers w
				WHERE w.node_id = ? AND w.status = 'ACTIVE' AND w.draining = 0
			) THEN 0 ELSE 1 END,
			n.last_heartbeat_at = UTC_TIMESTAMP(6)
		WHERE n.node_id = ?
	`, worker.NodeID, worker.NodeID, worker.NodeID, worker.NodeID, worker.NodeID)
	if err != nil {
		return err
	}
	return tx.Commit()
}

func (r *MySQL) RenewRuntimeExecutionLeases(
	ctx context.Context,
	workerID string,
	refs []model.RuntimeExecutionLeaseRef,
	extension time.Duration,
) (int64, error) {
	if len(refs) == 0 {
		return 0, nil
	}
	if extension <= 0 {
		extension = 15 * time.Second
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()

	leaseUntil := time.Now().UTC().Add(extension)
	var renewed int64
	for _, ref := range refs {
		if ref.JobID <= 0 || ref.ExecutionID == "" || ref.LeaseToken == "" {
			continue
		}
		res, execErr := tx.ExecContext(ctx, `
			UPDATE runtime_jobs
			SET lease_expires_at = ?
			WHERE id = ? AND execution_id = ? AND worker_id = ?
			  AND lease_token = ? AND status IN ('ACCEPTED','RESULT_PENDING','COMPLETING')
			  AND (? = 0 OR fence_epoch = ?)
		`, leaseUntil, ref.JobID, ref.ExecutionID, workerID, ref.LeaseToken,
			ref.FenceEpoch, ref.FenceEpoch)
		if execErr != nil {
			return 0, execErr
		}
		count, execErr := res.RowsAffected()
		if execErr != nil {
			return 0, execErr
		}
		renewed += count
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return renewed, nil
}

// RESULT_PENDING is only entered after a durable outbox INSERT. Unlike a live
// execution lease, a durably stored result must not be failed/replayed merely
// because its publisher or Kafka consumer is temporarily unavailable.
func (r *MySQL) MarkRuntimeJobResultPending(ctx context.Context, jobID int64, executionID, workerID, leaseToken string, fenceEpoch int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs SET status='RESULT_PENDING'
		WHERE id=? AND execution_id=? AND worker_id=? AND lease_token=?
		  AND fence_epoch=? AND status IN ('DISPATCHING','ACCEPTED')
	`, jobID, executionID, workerID, leaseToken, fenceEpoch)
	if err != nil {
		return false, err
	}
	count, err := res.RowsAffected()
	return count == 1, err
}

func scanRuntimeWorker(s scanner) (*model.RuntimeWorker, error) {
	var worker model.RuntimeWorker
	var circuit sql.NullTime
	var startedAt sql.NullTime
	var lastAssignment sql.NullTime
	err := s.Scan(
		&worker.WorkerID, &worker.NodeID, &worker.Zone, &worker.Version,
		&startedAt, &worker.Endpoint, &worker.Capacity, &worker.ActiveExecutions,
		&worker.AuthoritativeActive, &worker.NodeCapacity, &worker.NodeActive,
		&worker.SchedulingScore, &lastAssignment, &worker.Draining, &worker.Status,
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
	if startedAt.Valid {
		v := startedAt.Time
		worker.StartedAt = &v
	}
	if lastAssignment.Valid {
		v := lastAssignment.Time
		worker.LastAssignmentAt = &v
	}
	return &worker, nil
}

const runtimeWorkerSelect = `
	w.worker_id, w.node_id, w.zone, w.version, w.started_at, w.endpoint,
	w.capacity, w.active_executions,
	(SELECT COUNT(*) FROM runtime_jobs j
		WHERE j.worker_id = w.worker_id
		  AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')) AS authoritative_active,
	COALESCE(n.capacity, w.capacity) AS node_capacity,
	(SELECT COUNT(*) FROM runtime_jobs j
		WHERE j.node_id = w.node_id
		  AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')) AS node_active,
	(
		((SELECT COUNT(*) FROM runtime_jobs j
			WHERE j.worker_id = w.worker_id
			  AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')) / GREATEST(w.capacity, 1)) * 0.65
		+ ((SELECT COUNT(*) FROM runtime_jobs j
			WHERE j.node_id = w.node_id
			  AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')) / GREATEST(COALESCE(n.capacity, w.capacity), 1)) * 0.25
		+ LEAST(w.consecutive_failures, 10) * 0.01
	) AS scheduling_score,
	w.last_assignment_at, w.draining, w.status, w.consecutive_failures,
	w.circuit_open_until, w.last_heartbeat_at, w.created_at, w.updated_at
`

func (r *MySQL) RuntimeWorkerByID(ctx context.Context, workerID string) (*model.RuntimeWorker, error) {
	return scanRuntimeWorker(r.db.QueryRowContext(ctx, `
		SELECT `+runtimeWorkerSelect+`
		FROM runtime_workers w
		LEFT JOIN runtime_nodes n ON n.node_id = w.node_id
		WHERE w.worker_id = ? LIMIT 1
	`, workerID))
}

func (r *MySQL) ListAvailableRuntimeWorkers(ctx context.Context, staleBefore time.Time, limit int) ([]model.RuntimeWorker, error) {
	if limit <= 0 {
		limit = 32
	}
	rows, err := r.db.QueryContext(ctx, `
		SELECT `+runtimeWorkerSelect+`
		FROM runtime_workers w
		LEFT JOIN runtime_nodes n ON n.node_id = w.node_id
		WHERE w.status = 'ACTIVE'
		  AND w.draining = 0
		  AND w.last_heartbeat_at >= ?
		  AND (n.node_id IS NULL OR (n.status = 'ACTIVE' AND n.draining = 0 AND n.last_heartbeat_at >= ?))
		  AND (SELECT COUNT(*) FROM runtime_jobs j
			WHERE j.worker_id = w.worker_id
			  AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')) < w.capacity
		  AND (n.node_id IS NULL OR (SELECT COUNT(*) FROM runtime_jobs j
			WHERE j.node_id = w.node_id
			  AND j.status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')) < n.capacity)
		  AND (w.circuit_open_until IS NULL OR w.circuit_open_until <= UTC_TIMESTAMP(6))
		ORDER BY scheduling_score ASC,
			CASE WHEN w.last_assignment_at IS NULL THEN 0 ELSE 1 END ASC,
			w.last_assignment_at ASC, w.last_heartbeat_at DESC, w.worker_id ASC
		LIMIT ?
	`, staleBefore.UTC(), staleBefore.UTC(), limit)
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
	var nodeID string
	err = tx.QueryRowContext(ctx, `
		SELECT w.capacity, w.node_id
		FROM runtime_workers w
		LEFT JOIN runtime_nodes n ON n.node_id = w.node_id
		WHERE w.worker_id = ? AND w.status = 'ACTIVE' AND w.draining = 0
		  AND (n.node_id IS NULL OR (n.status = 'ACTIVE' AND n.draining = 0))
		FOR UPDATE
	`, workerID).Scan(&capacity, &nodeID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	var active int
	if err = tx.QueryRowContext(ctx, `
		SELECT COUNT(*) FROM runtime_jobs
		WHERE worker_id = ? AND status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')
	`, workerID).Scan(&active); err != nil {
		return nil, nil, err
	}
	if active >= capacity {
		return nil, nil, nil
	}

	// V3 serializes reservations at node level as well as worker level. Multiple
	// workers on the same machine must never exceed the node's declared capacity.
	if nodeID != "" {
		var nodeCapacity int
		err = tx.QueryRowContext(ctx, `
			SELECT capacity FROM runtime_nodes
			WHERE node_id = ? AND status = 'ACTIVE' AND draining = 0
			FOR UPDATE
		`, nodeID).Scan(&nodeCapacity)
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil, nil
		}
		if err != nil {
			return nil, nil, err
		}
		var nodeActive int
		if err = tx.QueryRowContext(ctx, `
			SELECT COUNT(*) FROM runtime_jobs
			WHERE node_id = ? AND status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')
		`, nodeID).Scan(&nodeActive); err != nil {
			return nil, nil, err
		}
		if nodeActive >= nodeCapacity {
			return nil, nil, nil
		}
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
		SET status = 'LEASED', worker_id = ?, node_id = ?, lease_token = ?,
			fence_epoch = fence_epoch + 1, lease_expires_at = ?,
			attempt_count = attempt_count + 1, last_error = NULL
		WHERE id = ? AND status = 'QUEUED'
	`, workerID, nodeID, leaseToken, leaseExpires, jobID)
	if err != nil {
		return nil, nil, err
	}
	affected, _ := res.RowsAffected()
	if affected != 1 {
		return nil, nil, ErrInvalidTaskState
	}

	if _, err = tx.ExecContext(ctx, `
		UPDATE runtime_workers SET last_assignment_at = UTC_TIMESTAMP(6)
		WHERE worker_id = ?
	`, workerID); err != nil {
		return nil, nil, err
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
		SET status = 'ACCEPTED', accepted_at = COALESCE(accepted_at, UTC_TIMESTAMP(6))
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
		WHERE id = ? AND status IN ('DISPATCHING','ACCEPTED','RESULT_PENDING') AND execution_id = ?
		  AND worker_id = ? AND lease_token = ?
	`, jobID, executionID, workerID, leaseToken)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	return affected == 1, err
}

func (r *MySQL) RuntimeJobCallbackOwned(ctx context.Context, jobID int64, executionID, workerID, leaseToken string) (bool, error) {
	var owned int
	err := r.db.QueryRowContext(ctx, `
		SELECT EXISTS(
			SELECT 1 FROM runtime_jobs
			WHERE id = ? AND status = 'COMPLETING' AND execution_id = ?
			  AND worker_id = ? AND lease_token = ?
		)
	`, jobID, executionID, workerID, leaseToken).Scan(&owned)
	if err != nil {
		return false, err
	}
	return owned == 1, nil
}

func (r *MySQL) MarkRuntimeJobCompleted(ctx context.Context, jobID int64) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs SET status = 'COMPLETED', lease_token = NULL,
			lease_expires_at = NULL, last_error = NULL
		WHERE id = ? AND status = 'COMPLETING'
	`, jobID)
	return err
}

// The task + assistant commit may survive a Go crash even if its job marker
// does not. Never mark a COMPLETING job FAILED merely because it exceeded a
// fixed 30-second window. After a generous replay window, reconcile only if
// the authoritative task has already reached a successful terminal state.
func (r *MySQL) ReconcileCommittedCompletingJobs(ctx context.Context, before time.Time) (int64, error) {
	res, err := r.db.ExecContext(ctx, `
		UPDATE runtime_jobs j INNER JOIN tasks t ON t.id=j.task_id
		SET j.status='COMPLETED', j.lease_token=NULL,
		    j.lease_expires_at=NULL, j.last_error=NULL
		WHERE j.status='COMPLETING' AND j.updated_at < ?
		  AND t.status IN ('COMPLETED','INPUT_REQUIRED','AUTH_REQUIRED')
	`, before.UTC())
	if err != nil {
		return 0, err
	}
	return res.RowsAffected()
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
		UPDATE runtime_jobs SET status = 'QUEUED', worker_id = NULL, node_id = NULL,
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
			UPDATE runtime_jobs SET status='QUEUED', worker_id=NULL, node_id=NULL, lease_token=NULL,
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

func (r *MySQL) RecoverLostAcceptedRuntimeJobs(
	ctx context.Context,
	now time.Time,
	retryDelay time.Duration,
	limit int,
) (int64, int64, error) {
	if limit <= 0 {
		limit = 50
	}
	if retryDelay < 0 {
		retryDelay = 0
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return 0, 0, err
	}
	defer func() { _ = tx.Rollback() }()

	type lostJob struct {
		jobID, taskID int64
		attempts, max int
		retrySafe     bool
		deadline      time.Time
	}
	rows, err := tx.QueryContext(ctx, `
		SELECT id, task_id, attempt_count, max_attempts, failover_retry_safe, deadline_at
		FROM runtime_jobs
		WHERE status = 'ACCEPTED'
		  AND lease_expires_at IS NOT NULL
		  AND lease_expires_at < ?
		ORDER BY id ASC
		LIMIT ?
		FOR UPDATE
	`, now.UTC(), limit)
	if err != nil {
		return 0, 0, err
	}
	lost := []lostJob{}
	for rows.Next() {
		var item lostJob
		if err := rows.Scan(&item.jobID, &item.taskID, &item.attempts, &item.max, &item.retrySafe, &item.deadline); err != nil {
			_ = rows.Close()
			return 0, 0, err
		}
		lost = append(lost, item)
	}
	if err := rows.Close(); err != nil {
		return 0, 0, err
	}

	var requeued int64
	var failed int64
	for _, item := range lost {
		canReplay := item.retrySafe && item.attempts < item.max && item.deadline.After(now)
		if canReplay {
			res, execErr := tx.ExecContext(ctx, `
				UPDATE runtime_jobs
				SET status='QUEUED', worker_id=NULL, node_id=NULL, lease_token=NULL,
					lease_expires_at=NULL, accepted_at=NULL, next_attempt_at=?,
					last_error='worker_execution_lease_expired_reassigned'
				WHERE id=? AND status='ACCEPTED'
			`, now.UTC().Add(retryDelay), item.jobID)
			if execErr != nil {
				return 0, 0, execErr
			}
			count, _ := res.RowsAffected()
			if count == 1 {
				requeued++
				if _, execErr = tx.ExecContext(ctx, `
					UPDATE tasks SET status='QUEUED', error_message=NULL
					WHERE id=? AND status='RUNNING'
				`, item.taskID); execErr != nil {
					return 0, 0, execErr
				}
			}
			continue
		}

		message := "worker lost after acceptance; automatic replay disabled"
		res, execErr := tx.ExecContext(ctx, `
			UPDATE runtime_jobs
			SET status='FAILED', lease_token=NULL, lease_expires_at=NULL, last_error=?
			WHERE id=? AND status='ACCEPTED'
		`, message, item.jobID)
		if execErr != nil {
			return 0, 0, execErr
		}
		count, _ := res.RowsAffected()
		if count == 1 {
			failed++
			if _, execErr = tx.ExecContext(ctx, `
				UPDATE tasks SET status='ERROR', error_message=?, continuation_json=NULL
				WHERE id=? AND status='RUNNING'
			`, message, item.taskID); execErr != nil {
				return 0, 0, execErr
			}
		}
	}

	if err := tx.Commit(); err != nil {
		return 0, 0, err
	}
	return requeued, failed, nil
}

func (r *MySQL) MarkStaleRuntimeTopology(ctx context.Context, staleBefore time.Time) (int64, int64, error) {
	workerRes, err := r.db.ExecContext(ctx, `
		UPDATE runtime_workers
		SET status='OFFLINE'
		WHERE status='ACTIVE' AND last_heartbeat_at < ?
	`, staleBefore.UTC())
	if err != nil {
		return 0, 0, err
	}
	nodeRes, err := r.db.ExecContext(ctx, `
		UPDATE runtime_nodes
		SET status='OFFLINE'
		WHERE status='ACTIVE' AND last_heartbeat_at < ?
	`, staleBefore.UTC())
	if err != nil {
		return 0, 0, err
	}
	workers, _ := workerRes.RowsAffected()
	nodes, _ := nodeRes.RowsAffected()
	return workers, nodes, nil
}

func (r *MySQL) ListExpiredAcceptedRuntimeJobs(ctx context.Context, now time.Time, limit int) ([]model.RuntimeJob, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := r.db.QueryContext(ctx, `
		SELECT `+runtimeJobColumns+` FROM runtime_jobs
		WHERE status IN ('DISPATCHING','ACCEPTED') AND deadline_at < ?
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

func (r *MySQL) AcquireRuntimeDispatcherLease(
	ctx context.Context,
	holderID string,
	duration time.Duration,
) (*model.RuntimeDispatcherLease, bool, error) {
	if duration <= 0 {
		duration = 5 * time.Second
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()

	// Dispatcher HA must use one authoritative clock. Control-plane replicas
	// may run on different hosts with small clock skew, so lease ownership is
	// decided using the MySQL clock rather than each process wall clock.
	var now time.Time
	if err = tx.QueryRowContext(ctx, `SELECT UTC_TIMESTAMP(6)`).Scan(&now); err != nil {
		return nil, false, err
	}
	now = now.UTC()
	leaseUntil := now.Add(duration)

	const leaseName = "durable-runtime-dispatcher"
	var current model.RuntimeDispatcherLease
	err = tx.QueryRowContext(ctx, `
		SELECT lease_name, holder_id, epoch, lease_until, last_heartbeat_at
		FROM runtime_dispatcher_leases
		WHERE lease_name = ?
		FOR UPDATE
	`, leaseName).Scan(
		&current.LeaseName, &current.HolderID, &current.Epoch,
		&current.LeaseUntil, &current.LastHeartbeatAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		current = model.RuntimeDispatcherLease{
			LeaseName: leaseName, HolderID: holderID, Epoch: 1,
			LeaseUntil: leaseUntil, LastHeartbeatAt: now,
		}
		_, err = tx.ExecContext(ctx, `
			INSERT INTO runtime_dispatcher_leases(
				lease_name, holder_id, epoch, lease_until, last_heartbeat_at
			) VALUES(?, ?, ?, ?, ?)
		`, current.LeaseName, current.HolderID, current.Epoch,
			current.LeaseUntil, current.LastHeartbeatAt)
		if err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return &current, true, nil
	}
	if err != nil {
		return nil, false, err
	}

	owned := current.HolderID == holderID
	if owned || !current.LeaseUntil.After(now) {
		if !owned {
			current.HolderID = holderID
			current.Epoch++
		}
		current.LeaseUntil = leaseUntil
		current.LastHeartbeatAt = now
		_, err = tx.ExecContext(ctx, `
			UPDATE runtime_dispatcher_leases
			SET holder_id = ?, epoch = ?, lease_until = ?, last_heartbeat_at = ?
			WHERE lease_name = ?
		`, current.HolderID, current.Epoch, current.LeaseUntil,
			current.LastHeartbeatAt, leaseName)
		if err != nil {
			return nil, false, err
		}
		owned = true
	}

	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return &current, owned, nil
}

func (r *MySQL) ReleaseRuntimeDispatcherLease(ctx context.Context, holderID string) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE runtime_dispatcher_leases
		SET lease_until = UTC_TIMESTAMP(6), last_heartbeat_at = UTC_TIMESTAMP(6)
		WHERE lease_name = 'durable-runtime-dispatcher' AND holder_id = ?
	`, holderID)
	return err
}

func (r *MySQL) RuntimeDispatcherLease(ctx context.Context) (*model.RuntimeDispatcherLease, error) {
	var lease model.RuntimeDispatcherLease
	err := r.db.QueryRowContext(ctx, `
		SELECT lease_name, holder_id, epoch, lease_until, last_heartbeat_at
		FROM runtime_dispatcher_leases
		WHERE lease_name = 'durable-runtime-dispatcher'
		LIMIT 1
	`).Scan(&lease.LeaseName, &lease.HolderID, &lease.Epoch,
		&lease.LeaseUntil, &lease.LastHeartbeatAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &lease, nil
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
		case "LEASED", "DISPATCHING":
			snapshot.Leased += count
		case "ACCEPTED", "RESULT_PENDING", "COMPLETING":
			snapshot.Accepted += count
		case "FAILED":
			snapshot.Failed = count
		case "CANCELED":
			snapshot.Canceled = count
		}
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}

	workerRow := r.db.QueryRowContext(ctx, `
		SELECT COUNT(*),
			COALESCE(SUM(CASE WHEN status='ACTIVE' AND draining=0 AND last_heartbeat_at>=?
				AND (circuit_open_until IS NULL OR circuit_open_until<=UTC_TIMESTAMP(6)) THEN 1 ELSE 0 END),0),
			COALESCE(SUM(CASE WHEN draining=1 THEN 1 ELSE 0 END),0),
			COALESCE(SUM(CASE WHEN circuit_open_until>UTC_TIMESTAMP(6) THEN 1 ELSE 0 END),0),
			COALESCE(SUM(CASE WHEN status='ACTIVE' AND last_heartbeat_at>=? THEN capacity ELSE 0 END),0)
		FROM runtime_workers
	`, staleBefore.UTC(), staleBefore.UTC())
	if err := workerRow.Scan(
		&snapshot.Workers, &snapshot.AvailableWorkers, &snapshot.DrainingWorkers,
		&snapshot.CircuitOpenWorkers, &snapshot.TotalCapacity,
	); err != nil {
		return nil, err
	}

	if err := r.db.QueryRowContext(ctx, `
		SELECT COUNT(*) FROM runtime_jobs
		WHERE status IN ('LEASED','DISPATCHING','ACCEPTED','RESULT_PENDING','COMPLETING')
	`).Scan(&snapshot.ActiveExecutions); err != nil {
		return nil, err
	}
	if snapshot.TotalCapacity > 0 {
		snapshot.UtilizationPercent = float64(snapshot.ActiveExecutions) / float64(snapshot.TotalCapacity) * 100
	}

	nodeRow := r.db.QueryRowContext(ctx, `
		SELECT COUNT(*),
			COALESCE(SUM(CASE WHEN status='ACTIVE' AND draining=0 AND last_heartbeat_at>=? THEN 1 ELSE 0 END),0),
			COALESCE(SUM(CASE WHEN status<>'ACTIVE' OR last_heartbeat_at<? THEN 1 ELSE 0 END),0)
		FROM runtime_nodes
	`, staleBefore.UTC(), staleBefore.UTC())
	if err := nodeRow.Scan(&snapshot.Nodes, &snapshot.AvailableNodes, &snapshot.StaleNodes); err != nil {
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
	if lease, err := r.RuntimeDispatcherLease(ctx); err != nil {
		return nil, err
	} else if lease != nil {
		snapshot.DispatcherEpoch = lease.Epoch
		snapshot.DispatcherLeaseRemain = time.Until(lease.LeaseUntil).Milliseconds()
		if snapshot.DispatcherLeaseRemain < 0 {
			snapshot.DispatcherLeaseRemain = 0
		}
	}
	return snapshot, nil
}

func (r *MySQL) RuntimeTopologySnapshot(ctx context.Context, staleBefore time.Time) (*model.RuntimeTopologySnapshot, error) {
	reliability, err := r.RuntimeReliabilitySnapshot(ctx, staleBefore)
	if err != nil {
		return nil, err
	}
	topology := &model.RuntimeTopologySnapshot{Reliability: *reliability}

	nodeRows, err := r.db.QueryContext(ctx, `
		SELECT node_id, zone, version, capacity, active_executions, worker_count,
			draining, status, last_heartbeat_at
		FROM runtime_nodes
		ORDER BY CASE WHEN status='ACTIVE' THEN 0 ELSE 1 END,
			zone ASC, node_id ASC
	`)
	if err != nil {
		return nil, err
	}
	for nodeRows.Next() {
		var node model.RuntimeNode
		if err := nodeRows.Scan(
			&node.NodeID, &node.Zone, &node.Version, &node.Capacity,
			&node.ActiveExecutions, &node.WorkerCount, &node.Draining,
			&node.Status, &node.LastHeartbeatAt,
		); err != nil {
			_ = nodeRows.Close()
			return nil, err
		}
		topology.Nodes = append(topology.Nodes, node)
	}
	if err := nodeRows.Close(); err != nil {
		return nil, err
	}

	workerRows, err := r.db.QueryContext(ctx, `
		SELECT `+runtimeWorkerSelect+`
		FROM runtime_workers w
		LEFT JOIN runtime_nodes n ON n.node_id = w.node_id
		ORDER BY CASE WHEN w.status='ACTIVE' THEN 0 ELSE 1 END,
			w.node_id ASC, w.worker_id ASC
	`)
	if err != nil {
		return nil, err
	}
	for workerRows.Next() {
		worker, err := scanRuntimeWorker(workerRows)
		if err != nil {
			_ = workerRows.Close()
			return nil, err
		}
		topology.Workers = append(topology.Workers, *worker)
	}
	if err := workerRows.Close(); err != nil {
		return nil, err
	}
	return topology, nil
}
