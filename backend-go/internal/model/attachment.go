package model

import "time"

// ConversationAttachment is a request-local asset uploaded for a single
// conversation. Attachments are not silently promoted into the knowledge base.
type ConversationAttachment struct {
	ID             int64     `json:"id"`
	UserID         int64     `json:"userId"`
	ConversationID int64     `json:"conversationId"`
	OriginalName   string    `json:"originalName"`
	MediaType      string    `json:"mediaType"`
	Extension      string    `json:"extension"`
	SizeBytes      int64     `json:"sizeBytes"`
	ChecksumSHA256 string    `json:"checksumSha256"`
	StorageKey     string    `json:"-"`
	CreatedAt      time.Time `json:"createdAt"`
}
