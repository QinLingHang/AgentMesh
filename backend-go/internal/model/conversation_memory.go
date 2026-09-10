package model

import "time"

// ConversationMemoryCapsule is a durable, compressed projection of one
// bounded range of conversation messages. Raw messages remain the source of
// truth in messages; capsules are only retrieval accelerators for model context.
type ConversationMemoryCapsule struct {
	ID              int64     `json:"id"`
	UserID          int64     `json:"userId"`
	ConversationID  int64     `json:"conversationId"`
	StartMessageID  int64     `json:"startMessageId"`
	EndMessageID    int64     `json:"endMessageId"`
	Summary         string    `json:"summary"`
	Facts           []string  `json:"facts"`
	Decisions       []string  `json:"decisions"`
	OpenTasks       []string  `json:"openTasks"`
	Entities        []string  `json:"entities"`
	Keywords        []string  `json:"keywords"`
	Importance      float64   `json:"importance"`
	SourceHash      string    `json:"sourceHash"`
	CompactionModel string    `json:"compactionModel"`
	InputTokens     int       `json:"inputTokens"`
	OutputTokens    int       `json:"outputTokens"`
	EstimatedCost   *float64  `json:"estimatedCost,omitempty"`
	CreatedAt       time.Time `json:"createdAt"`
	UpdatedAt       time.Time `json:"updatedAt"`
}

type ConversationMemoryCapsuleWrite struct {
	StartMessageID  int64    `json:"startMessageId"`
	EndMessageID    int64    `json:"endMessageId"`
	Summary         string   `json:"summary"`
	Facts           []string `json:"facts"`
	Decisions       []string `json:"decisions"`
	OpenTasks       []string `json:"openTasks"`
	Entities        []string `json:"entities"`
	Keywords        []string `json:"keywords"`
	Importance      float64  `json:"importance"`
	SourceHash      string   `json:"sourceHash"`
	CompactionModel string   `json:"compactionModel"`
	InputTokens     int      `json:"inputTokens"`
	OutputTokens    int      `json:"outputTokens"`
	EstimatedCost   *float64 `json:"estimatedCost,omitempty"`
}

type ConversationCompactionWindow struct {
	Items []Message `json:"items"`
}
