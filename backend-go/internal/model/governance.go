package model

import "time"

type Organization struct {
	ID        int64     `json:"id"`
	OwnerID   int64     `json:"ownerId"`
	Name      string    `json:"name"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type OrganizationMember struct {
	OrganizationID int64     `json:"organizationId"`
	UserID         int64     `json:"userId"`
	Email          string    `json:"email,omitempty"`
	DisplayName    string    `json:"displayName,omitempty"`
	Role           string    `json:"role"`
	CreatedAt      time.Time `json:"createdAt"`
	UpdatedAt      time.Time `json:"updatedAt"`
}

type ProjectMember struct {
	ProjectID   int64     `json:"projectId"`
	UserID      int64     `json:"userId"`
	Email       string    `json:"email,omitempty"`
	DisplayName string    `json:"displayName,omitempty"`
	Role        string    `json:"role"`
	CreatedAt   time.Time `json:"createdAt"`
	UpdatedAt   time.Time `json:"updatedAt"`
}

type ProjectQuota struct {
	ProjectID            int64   `json:"projectId"`
	RequestsPerMinute    int64   `json:"requestsPerMinute"`
	ConcurrentTasks      int64   `json:"concurrentTasks"`
	MonthlyTokenLimit    int64   `json:"monthlyTokenLimit"`
	MonthlyCostLimit     float64 `json:"monthlyCostLimit"`
	DailyToolActionLimit int64   `json:"dailyToolActionLimit"`
}

type ProjectUsage struct {
	ProjectID       int64   `json:"projectId"`
	MonthKey        string  `json:"monthKey"`
	RequestCount    int64   `json:"requestCount"`
	TokenCount      int64   `json:"tokenCount"`
	EstimatedCost   float64 `json:"estimatedCost"`
	ToolActionCount int64   `json:"toolActionCount"`
	ConcurrentTasks int64   `json:"concurrentTasks"`
}

type ProjectSecret struct {
	ID         int64      `json:"id"`
	ProjectID  int64      `json:"projectId"`
	Name       string     `json:"name"`
	Kind       string     `json:"kind"`
	MaskedHint string     `json:"maskedHint"`
	CreatedBy  int64      `json:"createdBy"`
	CreatedAt  time.Time  `json:"createdAt"`
	UpdatedAt  time.Time  `json:"updatedAt"`
	LastUsedAt *time.Time `json:"lastUsedAt,omitempty"`
}

type ProjectModelProvider struct {
	ProjectID int64     `json:"projectId"`
	Provider  string    `json:"provider"`
	BaseURL   string    `json:"baseUrl"`
	ModelName string    `json:"modelName"`
	SecretID  *int64    `json:"secretId,omitempty"`
	Enabled   bool      `json:"enabled"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type AuditEvent struct {
	ID           int64          `json:"id"`
	ProjectID    *int64         `json:"projectId,omitempty"`
	ActorUserID  int64          `json:"actorUserId"`
	Action       string         `json:"action"`
	ResourceType string         `json:"resourceType"`
	ResourceID   string         `json:"resourceId"`
	Result       string         `json:"result"`
	Metadata     map[string]any `json:"metadata,omitempty"`
	CreatedAt    time.Time      `json:"createdAt"`
}

type GovernanceOverview struct {
	Role          string                `json:"role"`
	Members       []ProjectMember       `json:"members"`
	Quota         ProjectQuota          `json:"quota"`
	Usage         ProjectUsage          `json:"usage"`
	Secrets       []ProjectSecret       `json:"secrets"`
	ModelProvider *ProjectModelProvider `json:"modelProvider,omitempty"`
	Audit         []AuditEvent          `json:"audit"`
}
