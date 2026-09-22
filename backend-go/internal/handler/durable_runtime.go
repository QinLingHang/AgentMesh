package handler

import (
	"encoding/json"
	"fmt"
	"net/http"
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

// TaskEvents uses authenticated fetch-SSE rather than EventSource because the
// browser stores its access token in memory. The task is re-authorized on each
// poll, not only when the connection is established. Sequence is persisted in
// MySQL; Last-Event-ID replays records after browser/gateway restart.
func (h *DurableRuntimeHandler) TaskEvents(c *gin.Context) {
	taskID, valid := idParam(c)
	if !valid {
		return
	}
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
	// Do not send event-stream headers before the first ownership/database check.
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
	// Reconnect periodically to force a fresh JWT middleware check.
	maxSession := time.NewTimer(45 * time.Second)
	defer maxSession.Stop()
	terminal := func(s string) bool {
		switch s {
		case "COMPLETED", "ERROR", "CANCELED", "FAILED", "INPUT_REQUIRED", "AUTH_REQUIRED":
			return true
		}
		return false
	}
	for {
		for _, e := range events {
			payload, encodeErr := json.Marshal(e)
			if encodeErr != nil {
				return
			}
			if _, writeErr := fmt.Fprintf(c.Writer, "id: %d\nevent: task\ndata: %s\n\n", e.Sequence, payload); writeErr != nil {
				return
			}
			after = e.Sequence
		}
		c.Writer.Flush()
		// A full page requires another fetch before terminal closure.
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
			// Never stream internal error strings or continue after authorization loss.
			_, _ = c.Writer.WriteString("event: access_lost\ndata: {}\n\n")
			c.Writer.Flush()
			return
		}
	}
}
