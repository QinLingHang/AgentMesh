package model

import "time"

type RunCostRecord struct {
	TaskID        int64      `json:"taskId"`
	UserID        int64      `json:"userId"`
	ProjectID     *int64     `json:"projectId,omitempty"`
	Provider      string     `json:"provider"`
	ModelName     string     `json:"modelName"`
	InputTokens   int64      `json:"inputTokens"`
	OutputTokens  int64      `json:"outputTokens"`
	TotalTokens   int64      `json:"totalTokens"`
	EstimatedCost float64    `json:"estimatedCost"`
	CostStatus    string     `json:"costStatus"`
	CreatedAt     time.Time  `json:"createdAt"`
	UpdatedAt     *time.Time `json:"updatedAt,omitempty"`
}

type CostBreakdown struct {
	Provider      string  `json:"provider"`
	ModelName     string  `json:"modelName"`
	Runs          int64   `json:"runs"`
	InputTokens   int64   `json:"inputTokens"`
	OutputTokens  int64   `json:"outputTokens"`
	TotalTokens   int64   `json:"totalTokens"`
	EstimatedCost float64 `json:"estimatedCost"`
}

type CostQuery struct {
	From      *time.Time
	To        *time.Time
	Provider  string
	ModelName string
}

type CostSummary struct {
	RunCount        int64           `json:"runCount"`
	InputTokens     int64           `json:"inputTokens"`
	OutputTokens    int64           `json:"outputTokens"`
	TotalTokens     int64           `json:"totalTokens"`
	EstimatedCost   float64         `json:"estimatedCost"`
	KnownCostRuns   int64           `json:"knownCostRuns"`
	UnknownCostRuns int64           `json:"unknownCostRuns"`
	Breakdown       []CostBreakdown `json:"breakdown"`
}
