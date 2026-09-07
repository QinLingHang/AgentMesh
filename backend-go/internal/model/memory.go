package model

import "time"

// UserMemory is long-term memory owned by one user.
//
// Scope invariant:
//   - ownership is user_id only
//   - there is intentionally no project_id
//   - Project Knowledge remains a separate project-scoped domain
//
// P3.1 only provides the durable CRUD foundation. Automatic extraction,
// semantic retrieval, prompt injection, and model-driven merging are added in
// later P3 stages.
type UserMemory struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Category string `json:"category"`

	MemoryKey string `json:"memoryKey"`

	Content string `json:"content"`

	SourceType string `json:"sourceType"`

	Confidence float64 `json:"confidence"`

	Status string `json:"status"`

	LastAccessedAt *time.Time `json:"lastAccessedAt"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

// MemoryFilter is intentionally lexical only in P3.1.
// Semantic/vector retrieval belongs to P3.3.
type MemoryFilter struct {
	Category string

	Status string

	Keyword string

	Limit int
}
