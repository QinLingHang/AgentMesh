package handler

import (
	"net/http"
	"strconv"
	"strings"

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

type workerHeartbeatReq struct {
	WorkerID         string `json:"workerId" binding:"required"`
	Endpoint         string `json:"endpoint" binding:"required"`
	Capacity         int    `json:"capacity"`
	ActiveExecutions int    `json:"activeExecutions"`
	Draining         bool   `json:"draining"`
}

func (h *DurableRuntimeHandler) Heartbeat(c *gin.Context) {
	var req workerHeartbeatReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40043, "Worker heartbeat 参数不合法")
		return
	}
	err := h.s.Heartbeat(c, model.RuntimeWorker{
		WorkerID:         strings.TrimSpace(req.WorkerID),
		Endpoint:         strings.TrimSpace(req.Endpoint),
		Capacity:         req.Capacity,
		ActiveExecutions: req.ActiveExecutions,
		Draining:         req.Draining,
	})
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, gin.H{"accepted": true})
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
