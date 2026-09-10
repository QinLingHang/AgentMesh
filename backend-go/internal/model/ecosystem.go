package model

import "time"

// ServiceAccount is a project-scoped machine identity used by the public API.
// The raw API key is intentionally never persisted or serialized after creation.
type ServiceAccount struct {
	ID           int64      `json:"id"`
	ProjectID    int64      `json:"projectId"`
	Name         string     `json:"name"`
	KeyPrefix    string     `json:"keyPrefix"`
	Scopes       []string   `json:"scopes"`
	Status       string     `json:"status"`
	CreatedBy    int64      `json:"createdBy"`
	ExpiresAt    *time.Time `json:"expiresAt,omitempty"`
	LastUsedAt   *time.Time `json:"lastUsedAt,omitempty"`
	RequestCount int64      `json:"requestCount"`
	ErrorCount   int64      `json:"errorCount"`
	CreatedAt    time.Time  `json:"createdAt"`
	UpdatedAt    time.Time  `json:"updatedAt"`
}

type ServiceAccountCredential struct {
	ServiceAccount ServiceAccount `json:"serviceAccount"`
	APIKey         string         `json:"apiKey"`
}

type APIPrincipal struct {
	ServiceAccountID int64    `json:"serviceAccountId"`
	ProjectID        int64    `json:"projectId"`
	ActorUserID      int64    `json:"actorUserId"`
	Scopes           []string `json:"scopes"`
}

type APIIdempotencyRecord struct {
	ServiceAccountID int64     `json:"serviceAccountId"`
	IdempotencyKey   string    `json:"idempotencyKey"`
	RequestHash      string    `json:"requestHash"`
	ResponseJSON     []byte    `json:"-"`
	Status           string    `json:"status"`
	CreatedAt        time.Time `json:"createdAt"`
}

type EcosystemAgentTemplate struct {
	Name         string   `json:"name"`
	Description  string   `json:"description,omitempty"`
	Endpoint     string   `json:"endpoint"`
	Protocol     string   `json:"protocol,omitempty"`
	Capabilities []string `json:"capabilities"`
	Provider     string   `json:"provider,omitempty"`
	ModelName    string   `json:"modelName,omitempty"`
}

type EcosystemMCPTemplate struct {
	Name             string `json:"name"`
	Transport        string `json:"transport,omitempty"`
	Endpoint         string `json:"endpoint"`
	ConnectTimeoutMS int64  `json:"connectTimeoutMs,omitempty"`
	CallTimeoutMS    int64  `json:"callTimeoutMs,omitempty"`
}

type EcosystemPluginTemplate struct {
	Name         string         `json:"name"`
	Description  string         `json:"description,omitempty"`
	Runtime      string         `json:"runtime,omitempty"`
	Entrypoint   string         `json:"entrypoint,omitempty"`
	Capabilities []string       `json:"capabilities,omitempty"`
	ConfigSchema map[string]any `json:"configSchema,omitempty"`
}

type EcosystemPackageManifest struct {
	SchemaVersion string                   `json:"schemaVersion"`
	Kind          string                   `json:"kind"`
	Permissions   []string                 `json:"permissions"`
	Agent         *EcosystemAgentTemplate  `json:"agent,omitempty"`
	MCP           *EcosystemMCPTemplate    `json:"mcp,omitempty"`
	Plugin        *EcosystemPluginTemplate `json:"plugin,omitempty"`
}

type EcosystemPackage struct {
	ID            int64     `json:"id"`
	OwnerUserID   int64     `json:"ownerUserId"`
	Slug          string    `json:"slug"`
	Name          string    `json:"name"`
	Kind          string    `json:"kind"`
	Summary       string    `json:"summary"`
	Description   string    `json:"description"`
	Visibility    string    `json:"visibility"`
	Status        string    `json:"status"`
	LatestVersion string    `json:"latestVersion,omitempty"`
	InstallCount  int64     `json:"installCount"`
	CreatedAt     time.Time `json:"createdAt"`
	UpdatedAt     time.Time `json:"updatedAt"`
}

type EcosystemPackageVersion struct {
	ID        int64                    `json:"id"`
	PackageID int64                    `json:"packageId"`
	Version   string                   `json:"version"`
	Manifest  EcosystemPackageManifest `json:"manifest"`
	Checksum  string                   `json:"checksum"`
	Status    string                   `json:"status"`
	CreatedBy int64                    `json:"createdBy"`
	CreatedAt time.Time                `json:"createdAt"`
}

type EcosystemPackageDetail struct {
	Package  EcosystemPackage          `json:"package"`
	Versions []EcosystemPackageVersion `json:"versions"`
}

type EcosystemPackageBundle struct {
	FormatVersion string                  `json:"formatVersion"`
	Package       EcosystemPackage        `json:"package"`
	Version       EcosystemPackageVersion `json:"version"`
}

type ProjectPackageInstallation struct {
	ID           int64          `json:"id"`
	ProjectID    int64          `json:"projectId"`
	PackageID    int64          `json:"packageId"`
	VersionID    int64          `json:"versionId"`
	PackageSlug  string         `json:"packageSlug"`
	PackageName  string         `json:"packageName"`
	Kind         string         `json:"kind"`
	Version      string         `json:"version"`
	Enabled      bool           `json:"enabled"`
	Config       map[string]any `json:"config,omitempty"`
	ResourceType string         `json:"resourceType,omitempty"`
	ResourceID   *int64         `json:"resourceId,omitempty"`
	InstalledBy  int64          `json:"installedBy"`
	CreatedAt    time.Time      `json:"createdAt"`
	UpdatedAt    time.Time      `json:"updatedAt"`
}

type EcosystemOverview struct {
	PublishedPackages int64 `json:"publishedPackages"`
	AgentPackages     int64 `json:"agentPackages"`
	MCPPackages       int64 `json:"mcpPackages"`
	PluginPackages    int64 `json:"pluginPackages"`
	TotalInstalls     int64 `json:"totalInstalls"`
}
