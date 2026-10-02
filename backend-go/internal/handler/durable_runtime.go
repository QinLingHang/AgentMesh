package handler

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"

	"github.com/gin-gonic/gin"
)

type DurableRuntimeHandler struct {
	s *service.DurableRuntimeService
}

func NewDurableRuntimeHandler(s *service.DurableRuntimeService) *DurableRuntimeHandler {
	return &DurableRuntimeHandler{s: s}
}

func (h *DurableRuntimeHandler) Run(c *gin.Context) {
	var req runReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40042, "Task 参数不合法")
		return
	}
	result, err := h.s.Run(c, uid(c), service.RunTaskInput{
		ClientRequestID: req.ClientRequestID, ConversationID: req.ConversationID,
		Task:           req.Task,
		Scheduler:      req.Scheduler,
		Planner:        req.Planner,
		ExecutionMode:  req.ExecutionMode,
		SynthesisMode:  req.SynthesisMode,
		ModelSelection: req.ModelSelection,
		AttachmentIDs:  req.AttachmentIDs,
		RagPolicy:      req.RagPolicy,
		Constraints:    req.Constraints,
	})
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, result)
}

func (h *DurableRuntimeHandler) Cancel(c *gin.Context) {
	taskID, valid := idParam(c)
	if !valid {
		return
	}
	task, err := h.s.Cancel(c, uid(c), taskID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, task)
}

func (h *DurableRuntimeHandler) Reliability(c *gin.Context) {
	snapshot, err := h.s.Reliability(c)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, snapshot)
}

func (h *DurableRuntimeHandler) Topology(c *gin.Context) {
	topology, err := h.s.Topology(c)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, topology)
}

type workerExecutionLeaseReq struct {
	JobID         int64  `json:"jobId"`
	ExecutionID   string `json:"executionId"`
	LeaseToken    string `json:"leaseToken"`
	FenceEpoch    int64  `json:"fenceEpoch"`
	ResultPending bool   `json:"resultPending"`
}

type workerHeartbeatReq struct {
	WorkerID         string                    `json:"workerId" binding:"required"`
	NodeID           string                    `json:"nodeId"`
	Zone             string                    `json:"zone"`
	Version          string                    `json:"version"`
	StartedAt        *time.Time                `json:"startedAt"`
	Endpoint         string                    `json:"endpoint" binding:"required"`
	Capacity         int                       `json:"capacity"`
	NodeCapacity     int                       `json:"nodeCapacity"`
	ActiveExecutions int                       `json:"activeExecutions"`
	Draining         bool                      `json:"draining"`
	ExecutionLeases  []workerExecutionLeaseReq `json:"executionLeases"`
}

func (h *DurableRuntimeHandler) Heartbeat(c *gin.Context) {
	var req workerHeartbeatReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40043, "Worker heartbeat 参数不合法")
		return
	}
	leases := make([]model.RuntimeExecutionLeaseRef, 0, len(req.ExecutionLeases))
	for _, item := range req.ExecutionLeases {
		leases = append(leases, model.RuntimeExecutionLeaseRef{
			JobID: item.JobID, ExecutionID: strings.TrimSpace(item.ExecutionID),
			LeaseToken: strings.TrimSpace(item.LeaseToken), FenceEpoch: item.FenceEpoch,
			ResultPending: item.ResultPending,
		})
	}
	terminalIDs, err := h.s.Heartbeat(c, model.RuntimeWorker{
		WorkerID:         strings.TrimSpace(req.WorkerID),
		NodeID:           strings.TrimSpace(req.NodeID),
		Zone:             strings.TrimSpace(req.Zone),
		Version:          strings.TrimSpace(req.Version),
		StartedAt:        req.StartedAt,
		Endpoint:         strings.TrimSpace(req.Endpoint),
		Capacity:         req.Capacity,
		NodeCapacity:     req.NodeCapacity,
		ActiveExecutions: req.ActiveExecutions,
		Draining:         req.Draining,
	}, leases)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, gin.H{"accepted": true, "terminalExecutionIds": terminalIDs})
}

func (h *DurableRuntimeHandler) Callback(c *gin.Context) {
	jobID, err := strconv.ParseInt(c.Param("jobId"), 10, 64)
	if err != nil || jobID <= 0 {
		fail(c, http.StatusBadRequest, 40044, "Runtime Job ID 不合法")
		return
	}
	var callback service.DurableExecutionCallback
	if c.ShouldBindJSON(&callback) != nil {
		fail(c, http.StatusBadRequest, 40045, "Runtime callback 参数不合法")
		return
	}
	if err := h.s.Callback(c, jobID, callback); err != nil {
		domain(c, err)
		return
	}
	ok(c, gin.H{"accepted": true})
}

// WorkerPhase uses the internal-token-protected route. Job ownership, lease,
// fence and live status are verified atomically by the repository before INSERT.
func (h *DurableRuntimeHandler) WorkerPhase(c *gin.Context) {
	jobID, err := strconv.ParseInt(c.Param("jobId"), 10, 64)
	if err != nil || jobID <= 0 {
		fail(c, http.StatusBadRequest, 40044, "Runtime Job ID 不合法")
		return
	}
	var phase service.DurableWorkerPhase
	if c.ShouldBindJSON(&phase) != nil {
		fail(c, http.StatusBadRequest, 40047, "Worker phase 参数不合法")
		return
	}
	accepted, err := h.s.WorkerPhase(c.Request.Context(), jobID, phase)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, gin.H{"accepted": accepted})
}

// WorkerStream admits only model answer deltas from the internal worker. The
// service validates worker/lease/fence ownership and stores the chunk in the
// bounded Redis replay stream; business completion never depends on this path.
func (h *DurableRuntimeHandler) WorkerStream(c *gin.Context) {
	jobID, err := strconv.ParseInt(c.Param("jobId"), 10, 64)
	if err != nil || jobID <= 0 {
		fail(c, http.StatusBadRequest, 40044, "Runtime Job ID 不合法")
		return
	}
	var event service.DurableWorkerDelta
	if c.ShouldBindJSON(&event) != nil {
		fail(c, http.StatusBadRequest, 40048, "Worker stream 参数不合法")
		return
	}
	accepted, err := h.s.WorkerDelta(c.Request.Context(), jobID, event)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, gin.H{"accepted": accepted})
}

func (h *DurableRuntimeHandler) taskEventsLegacy(c *gin.Context, taskID int64) {
	cursor := strings.TrimSpace(c.GetHeader("Last-Event-ID"))
	if cursor == "" {
		cursor = strings.TrimSpace(c.Query("after"))
	}
	var after int64
	if cursor != "" {
		parsed, err := strconv.ParseInt(cursor, 10, 64)
		if err != nil || parsed < 0 {
			fail(c, http.StatusBadRequest, 40046, "事件游标不合法")
			return
		}
		after = parsed
	}
	events, status, err := h.s.TaskEvents(c.Request.Context(), uid(c), taskID, after)
	if err != nil {
		domain(c, err)
		return
	}
	c.Header("Content-Type", "text/event-stream; charset=utf-8")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("X-Accel-Buffering", "no")
	c.Header("Connection", "keep-alive")
	c.Status(http.StatusOK)
	_, _ = c.Writer.WriteString("retry: 1500\n\n")
	c.Writer.Flush()
	poll := time.NewTicker(500 * time.Millisecond)
	defer poll.Stop()
	keepalive := time.NewTicker(10 * time.Second)
	defer keepalive.Stop()
	maxSession := time.NewTimer(45 * time.Second)
	defer maxSession.Stop()
	terminal := func(status string) bool {
		switch status {
		case "COMPLETED", "ERROR", "CANCELED", "FAILED", "INPUT_REQUIRED", "AUTH_REQUIRED":
			return true
		}
		return false
	}
	for {
		for _, event := range events {
			payload, encodeErr := json.Marshal(event)
			if encodeErr != nil {
				return
			}
			if _, writeErr := fmt.Fprintf(c.Writer, "id: %d\nevent: task\ndata: %s\n\n", event.Sequence, payload); writeErr != nil {
				return
			}
			after = event.Sequence
		}
		c.Writer.Flush()
		if terminal(status) && len(events) < 100 {
			return
		}
		select {
		case <-c.Request.Context().Done():
			return
		case <-maxSession.C:
			return
		case <-keepalive.C:
			if _, err := c.Writer.WriteString(": keepalive\n\n"); err != nil {
				return
			}
			c.Writer.Flush()
		case <-poll.C:
		}
		events, status, err = h.s.TaskEvents(c.Request.Context(), uid(c), taskID, after)
		if err != nil {
			_, _ = c.Writer.WriteString("event: access_lost\ndata: {}\n\n")
			c.Writer.Flush()
			return
		}
	}
}

// TaskEvents uses authenticated fetch-SSE rather than EventSource because the
// browser stores its access token in memory. The task is re-authorized on each
// poll, not only when the connection is established. State sequence remains
// persisted in MySQL while live answer chunks use a bounded Redis cursor; the
// opt-in composite Last-Event-ID replays both after browser/gateway reconnect.
func (h *DurableRuntimeHandler) TaskEvents(c *gin.Context) {
	taskID, valid := idParam(c)
	if !valid {
		return
	}
	// Preserve the state-only numeric-cursor contract for the frozen React
	// rollback client. Vue opts into P25's composite state+delta cursor.
	if c.GetHeader("X-AgentMesh-Stream-Protocol") != "durable-live-v1" {
		h.taskEventsLegacy(c, taskID)
		return
	}
	rawCursor := strings.TrimSpace(c.GetHeader("Last-Event-ID"))
	if rawCursor == "" {
		rawCursor = strings.TrimSpace(c.Query("after"))
	}
	cursor, err := parseDurableSSECursor(rawCursor)
	if err != nil {
		fail(c, http.StatusBadRequest, 40046, "事件游标不合法")
		return
	}

	type streamBatch struct {
		states    []model.DurableTaskEvent
		deltas    []model.DurableLiveDelta
		snapshot  model.DurableTaskStreamSnapshot
		needReset bool
	}
	load := func() (streamBatch, error) {
		states, snapshot, loadErr := h.s.TaskEventBatch(c.Request.Context(), uid(c), taskID, cursor.State)
		if loadErr != nil {
			return streamBatch{}, loadErr
		}
		needReset := false
		if snapshot.FenceEpoch > 0 && cursor.Fence != snapshot.FenceEpoch {
			needReset = cursor.Fence > 0
			cursor.Fence = snapshot.FenceEpoch
			// Redis stream IDs are fence-ordinal. Starting at fence-0 replays
			// only the authoritative attempt and skips abandoned worker text.
			cursor.Delta = fmt.Sprintf("%d-0", snapshot.FenceEpoch)
		}
		deltas, liveErr := h.s.TaskLiveDeltas(c.Request.Context(), taskID, cursor.Delta)
		if liveErr != nil {
			// Live output is fail-open by design. State/terminal replay from
			// MySQL remains authoritative and a refresh restores the final answer.
			deltas = nil
		}
		filtered := deltas[:0]
		for _, delta := range deltas {
			if delta.TaskID == taskID && delta.ExecutionID == snapshot.ExecutionID && delta.FenceEpoch == snapshot.FenceEpoch {
				filtered = append(filtered, delta)
			}
		}
		return streamBatch{states: states, deltas: filtered, snapshot: snapshot, needReset: needReset}, nil
	}

	batch, err := load()
	if err != nil {
		domain(c, err)
		return
	}
	c.Header("Content-Type", "text/event-stream; charset=utf-8")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("X-Accel-Buffering", "no")
	c.Header("Connection", "keep-alive")
	c.Status(http.StatusOK)
	_, _ = c.Writer.WriteString("retry: 1500\n\n")
	c.Writer.Flush()

	poll := time.NewTicker(250 * time.Millisecond)
	defer poll.Stop()
	keepalive := time.NewTicker(10 * time.Second)
	defer keepalive.Stop()
	// Reconnect periodically to force a fresh JWT middleware check.
	maxSession := time.NewTimer(45 * time.Second)
	defer maxSession.Stop()
	terminal := func(status string) bool {
		switch status {
		case "COMPLETED", "ERROR", "CANCELED", "FAILED", "INPUT_REQUIRED", "AUTH_REQUIRED":
			return true
		}
		return false
	}

	emitReset := func(fence int64) error {
		payload, _ := json.Marshal(gin.H{"taskId": taskID, "fenceEpoch": fence})
		_, writeErr := fmt.Fprintf(c.Writer, "id: %s\nevent: stream_reset\ndata: %s\n\n", formatDurableSSECursor(cursor), payload)
		return writeErr
	}
	emitState := func(event model.DurableTaskEvent) error {
		payload, encodeErr := json.Marshal(event)
		if encodeErr != nil {
			return encodeErr
		}
		cursor.State = event.Sequence
		_, writeErr := fmt.Fprintf(c.Writer, "id: %s\nevent: task\ndata: %s\n\n", formatDurableSSECursor(cursor), payload)
		return writeErr
	}
	emitDelta := func(event model.DurableLiveDelta) error {
		payload, encodeErr := json.Marshal(event)
		if encodeErr != nil {
			return encodeErr
		}
		cursor.Delta = event.StreamID
		_, writeErr := fmt.Fprintf(c.Writer, "id: %s\nevent: delta\ndata: %s\n\n", formatDurableSSECursor(cursor), payload)
		return writeErr
	}

	for {
		if batch.needReset {
			if err := emitReset(batch.snapshot.FenceEpoch); err != nil {
				return
			}
		}

		type orderedEvent struct {
			createdAt time.Time
			state     *model.DurableTaskEvent
			delta     *model.DurableLiveDelta
		}
		ordered := make([]orderedEvent, 0, len(batch.states)+len(batch.deltas))
		for i := range batch.states {
			event := &batch.states[i]
			ordered = append(ordered, orderedEvent{createdAt: event.CreatedAt, state: event})
		}
		for i := range batch.deltas {
			event := &batch.deltas[i]
			ordered = append(ordered, orderedEvent{createdAt: event.CreatedAt, delta: event})
		}
		sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].createdAt.Before(ordered[j].createdAt) })
		for _, item := range ordered {
			if item.state != nil {
				if err := emitState(*item.state); err != nil {
					return
				}
				continue
			}
			if item.delta != nil {
				if err := emitDelta(*item.delta); err != nil {
					return
				}
			}
		}
		c.Writer.Flush()

		// Both stores are bounded pages. Close only after the terminal MySQL
		// state and the current Redis delta page have both been drained.
		if terminal(batch.snapshot.Status) && len(batch.states) < 100 && len(batch.deltas) < 256 {
			return
		}
		select {
		case <-c.Request.Context().Done():
			return
		case <-maxSession.C:
			return
		case <-keepalive.C:
			if _, err := c.Writer.WriteString(": keepalive\n\n"); err != nil {
				return
			}
			c.Writer.Flush()
		case <-poll.C:
		}
		batch, err = load()
		if err != nil {
			// Never stream internal error strings or continue after authorization loss.
			_, _ = c.Writer.WriteString("event: access_lost\ndata: {}\n\n")
			c.Writer.Flush()
			return
		}
	}
}
