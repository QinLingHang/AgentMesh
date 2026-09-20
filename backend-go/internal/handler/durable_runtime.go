package handler

import (
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
		ConversationID: req.ConversationID,
		Task:           req.Task,
		Scheduler:      req.Scheduler,
		Planner:        req.Planner,
		ExecutionMode:  req.ExecutionMode,
		SynthesisMode:  req.SynthesisMode,
		ModelSelection: req.ModelSelection,
		HarnessConfig:  req.HarnessConfig,
		AttachmentIDs:  req.AttachmentIDs,
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
