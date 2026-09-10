package model

import "time"

// ModelSelection captures the task-level model routing preference submitted by
// the browser. "auto" lets AgentMesh choose from the user's enabled auto-route
// model pool. "manual" pins the request to ServiceID after normal ownership,
// BYOK and governance checks.
type ModelSelection struct {
	Mode      string `json:"mode"`
	ServiceID *int64 `json:"serviceId,omitempty"`
}

// UserModelProvider is the legacy browser-safe representation of a user's
// single personal BYOK model configuration. It is retained for API/backward
// compatibility while the product now stores multiple UserModelService rows.
// The API key plaintext is never returned.
type UserModelProvider struct {
	UserID          int64     `json:"userId"`
	Provider        string    `json:"provider"`
	BaseURL         string    `json:"baseUrl"`
	ModelName       string    `json:"modelName"`
	VisionModelName string    `json:"visionModelName"`
	MaskedHint      string    `json:"maskedHint"`
	Enabled         bool      `json:"enabled"`
	CreatedAt       time.Time `json:"createdAt"`
	UpdatedAt       time.Time `json:"updatedAt"`
}

// UserModelProviderInput keeps the legacy single-provider write contract.
// APIKey may be empty when updating an existing provider, in which case the
// stored encrypted key is preserved.
type UserModelProviderInput struct {
	Provider        string `json:"provider"`
	BaseURL         string `json:"baseUrl"`
	ModelName       string `json:"modelName"`
	VisionModelName string `json:"visionModelName"`
	APIKey          string `json:"apiKey"`
	Enabled         bool   `json:"enabled"`
}

// UserModelService is a browser-safe entry in the user's personal model pool.
// ServiceKey is an internal immutable identifier used only as AEAD associated
// data and is never exposed to the browser. Ciphertext is stored separately in
// the repository and plaintext API keys never leave the trusted request path.
type UserModelService struct {
	ID              int64     `json:"id"`
	ServiceKey      string    `json:"-"`
	UserID          int64     `json:"userId"`
	Name            string    `json:"name"`
	Provider        string    `json:"provider"`
	BaseURL         string    `json:"baseUrl"`
	ModelName       string    `json:"modelName"`
	VisionModelName string    `json:"visionModelName"`
	MaskedHint      string    `json:"maskedHint"`
	Enabled         bool      `json:"enabled"`
	AutoRoute       bool      `json:"autoRoute"`
	IsDefault       bool      `json:"isDefault"`
	CreatedAt       time.Time `json:"createdAt"`
	UpdatedAt       time.Time `json:"updatedAt"`
}

// UserModelServiceInput accepts plaintext only on create/update. APIKey may be
// empty on update, which preserves the existing encrypted credential.
type UserModelServiceInput struct {
	Name            string `json:"name"`
	Provider        string `json:"provider"`
	BaseURL         string `json:"baseUrl"`
	ModelName       string `json:"modelName"`
	VisionModelName string `json:"visionModelName"`
	APIKey          string `json:"apiKey"`
	Enabled         bool   `json:"enabled"`
	AutoRoute       bool   `json:"autoRoute"`
	IsDefault       bool   `json:"isDefault"`
}
