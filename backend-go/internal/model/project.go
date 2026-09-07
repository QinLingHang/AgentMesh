package model

import "time"

// Project is a workspace container for conversations.
//
// We intentionally keep conversation membership in a separate
// project_conversations table rather than adding project_id to the
// existing conversations table. That makes project deletion non-destructive:
// deleting a project only removes the grouping and preserves conversations.
type Project struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Name string `json:"name"`

	Description string `json:"description"`

	ConversationIDs []int64 `json:"conversationIds"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}
