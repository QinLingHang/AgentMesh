package model

import "time"

// UserModelProvider is the browser-safe representation of a user's personal
// BYOK model configuration. The API key plaintext is never returned.
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

// UserModelProviderInput accepts plaintext only on write. APIKey may be empty
// when updating an existing provider, in which case the stored encrypted key is
// preserved.
type UserModelProviderInput struct {
	Provider        string `json:"provider"`
	BaseURL         string `json:"baseUrl"`
	ModelName       string `json:"modelName"`
	VisionModelName string `json:"visionModelName"`
	APIKey          string `json:"apiKey"`
	Enabled         bool   `json:"enabled"`
}
