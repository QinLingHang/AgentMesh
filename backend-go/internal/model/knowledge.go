package model

import "time"

type KnowledgeBaseScope string

const (
	KnowledgeBaseScopeGlobal  KnowledgeBaseScope = "GLOBAL"
	KnowledgeBaseScopeProject KnowledgeBaseScope = "PROJECT"
)

type KnowledgeBase struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Name string `json:"name"`

	Description string `json:"description"`

	Scope KnowledgeBaseScope `json:"scope"`

	ProjectID *int64 `json:"projectId"`

	ProjectName string `json:"projectName,omitempty"`

	IsDefault bool `json:"isDefault"`

	FileCount int `json:"fileCount"`

	ReadyFileCount int `json:"readyFileCount"`

	PendingFileCount int `json:"pendingFileCount"`

	ErrorFileCount int `json:"errorFileCount"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

type KnowledgeFile struct {
	ID int64 `json:"id"`

	KnowledgeBaseID int64 `json:"knowledgeBaseId"`

	KnowledgeBaseName string `json:"knowledgeBaseName"`

	Scope KnowledgeBaseScope `json:"scope"`

	ProjectID *int64 `json:"projectId"`

	ProjectName string `json:"projectName,omitempty"`

	UserID int64 `json:"userId"`

	OriginalName string `json:"originalName"`

	MediaType string `json:"mediaType"`

	Extension string `json:"extension"`

	SizeBytes int64 `json:"sizeBytes"`

	ChecksumSHA256 string `json:"checksumSha256"`

	StorageKey string `json:"storageKey"`

	Status string `json:"status"`

	ChunkCount int `json:"chunkCount"`

	TextChunkCount int `json:"textChunkCount"`

	VisualEvidenceCount int `json:"visualEvidenceCount"`

	PageCount int `json:"pageCount"`

	VisualStatus string `json:"visualStatus"`

	VisualErrorMessage *string `json:"visualErrorMessage,omitempty"`

	ErrorMessage *string `json:"errorMessage"`

	IndexedAt *time.Time `json:"indexedAt"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

// KnowledgeIndexResult is the persistence-facing summary of one knowledge
// ingestion run.  It intentionally lives in the domain model so repository
// code does not depend on the HTTP runtime client package.
type KnowledgeIndexResult struct {
	ChunkCount          int
	TextChunkCount      int
	VisualEvidenceCount int
	PageCount           int
	VisualStatus        string
	VisualError         string
}

type RuntimeKnowledgeScope struct {
	UserID int64 `json:"userId"`

	ConversationID *int64 `json:"conversationId"`

	ProjectID *int64 `json:"projectId"`

	Mode string `json:"mode"`

	KnowledgeBaseIDs []int64 `json:"knowledgeBaseIds"`
}
