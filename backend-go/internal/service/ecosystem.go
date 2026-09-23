package service

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

var ErrAPIKeyInvalid = errors.New("invalid api key")
var ErrAPIScopeDenied = errors.New("api scope denied")
var ErrIdempotencyConflict = errors.New("idempotency conflict")
var ErrPackageValidation = errors.New("package validation failed")

type ecosystemRepository interface {
	CreateServiceAccount(context.Context, model.ServiceAccount, string) (*model.ServiceAccount, error)
	ServiceAccountByID(context.Context, int64, int64) (*model.ServiceAccount, error)
	ServiceAccountByPrefix(context.Context, string) (*model.ServiceAccount, string, error)
	ListServiceAccounts(context.Context, int64) ([]model.ServiceAccount, error)
	RevokeServiceAccount(context.Context, int64, int64) (bool, error)
	TouchServiceAccount(context.Context, int64) error
	RecordAPIUsage(context.Context, int64, int64, int, int64) error
	APIIdempotencyRecord(context.Context, int64, string) (*model.APIIdempotencyRecord, error)
	ReserveAPIIdempotencyRecord(context.Context, model.APIIdempotencyRecord) (bool, error)
	CompleteAPIIdempotencyRecord(context.Context, int64, string, []byte) error
	DeleteAPIIdempotencyReservation(context.Context, int64, string) error

	CreateEcosystemPackage(context.Context, model.EcosystemPackage) (*model.EcosystemPackage, error)
	EcosystemPackageByID(context.Context, int64) (*model.EcosystemPackage, error)
	EcosystemPackageBySlug(context.Context, string) (*model.EcosystemPackage, error)
	SearchEcosystemPackages(context.Context, string, string, *int64, int) ([]model.EcosystemPackage, error)
	CreateEcosystemPackageVersion(context.Context, model.EcosystemPackageVersion) (*model.EcosystemPackageVersion, error)
	EcosystemPackageVersion(context.Context, int64, string) (*model.EcosystemPackageVersion, error)
	EcosystemPackageVersionByID(context.Context, int64) (*model.EcosystemPackageVersion, error)
	ListEcosystemPackageVersions(context.Context, int64) ([]model.EcosystemPackageVersion, error)
	PublishEcosystemPackage(context.Context, int64, string) error
	EcosystemOverview(context.Context) (model.EcosystemOverview, error)

	UpsertProjectPackageInstallation(context.Context, model.ProjectPackageInstallation) (*model.ProjectPackageInstallation, error)
	IncrementEcosystemPackageInstallCount(context.Context, int64) error
	ProjectPackageInstallationByPackage(context.Context, int64, int64) (*model.ProjectPackageInstallation, error)
	ProjectPackageInstallationByID(context.Context, int64, int64) (*model.ProjectPackageInstallation, error)
	ListProjectPackageInstallations(context.Context, int64) ([]model.ProjectPackageInstallation, error)
	UpdateProjectPackageInstallationState(context.Context, int64, int64, bool, string, *int64) (*model.ProjectPackageInstallation, error)
	DeleteProjectPackageInstallation(context.Context, int64, int64) (bool, error)

	ProjectByID(context.Context, int64, int64) (*model.Project, error)
	ProjectIDByConversation(context.Context, int64, int64) (*int64, error)
	TaskByID(context.Context, int64, int64) (*model.Task, error)
	AppendAudit(context.Context, model.AuditEvent) error
}

type EcosystemService struct {
	repo          ecosystemRepository
	governance    *GovernanceService
	conversations *ConversationService
	projects      *ProjectService
	tasks         *TaskService
	agents        *AgentService
	mcp           *MCPServerService
}

func NewEcosystemService(
	repo ecosystemRepository,
	governance *GovernanceService,
	conversations *ConversationService,
	projects *ProjectService,
	tasks *TaskService,
	agents *AgentService,
	mcp *MCPServerService,
) *EcosystemService {
	return &EcosystemService{
		repo: repo, governance: governance, conversations: conversations,
		projects: projects, tasks: tasks, agents: agents, mcp: mcp,
	}
}

var serviceAccountScopes = map[string]struct{}{
	"tasks:read":       {},
	"tasks:write":      {},
	"marketplace:read": {},
	"ecosystem:read":   {},
}

var packagePermissions = map[string]struct{}{
	"knowledge:read":   {},
	"memory:read":      {},
	"tools:invoke":     {},
	"tasks:submit":     {},
	"network:outbound": {},
	"mcp:connect":      {},
}

func normalizeStringSet(values []string, allowed map[string]struct{}) ([]string, error) {
	seen := map[string]struct{}{}
	out := []string{}
	for _, value := range values {
		value = strings.ToLower(strings.TrimSpace(value))
		if value == "" {
			continue
		}
		if _, ok := allowed[value]; !ok {
			return nil, ErrInvalidInput
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	sort.Strings(out)
	return out, nil
}

func randomBytes(n int) ([]byte, error) {
	value := make([]byte, n)
	_, err := rand.Read(value)
	return value, err
}

func serviceAccountSecretHash(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return strings.ToUpper(hex.EncodeToString(sum[:]))
}

func createServiceAccountKey() (string, string, error) {
	prefixBytes, err := randomBytes(8)
	if err != nil {
		return "", "", err
	}
	secretBytes, err := randomBytes(32)
	if err != nil {
		return "", "", err
	}
	prefix := hex.EncodeToString(prefixBytes)
	keyPrefix := "am_sk_" + prefix
	raw := keyPrefix + "_" + base64.RawURLEncoding.EncodeToString(secretBytes)
	return raw, keyPrefix, nil
}

func parseServiceAccountPrefix(raw string) string {
	raw = strings.TrimSpace(raw)
	if !strings.HasPrefix(raw, "am_sk_") {
		return ""
	}
	rest := strings.TrimPrefix(raw, "am_sk_")
	index := strings.Index(rest, "_")
	if index <= 0 {
		return ""
	}
	prefix := rest[:index]
	if len(prefix) != 16 {
		return ""
	}
	return "am_sk_" + prefix
}

func hasScope(scopes []string, wanted string) bool {
	for _, scope := range scopes {
		if scope == wanted {
			return true
		}
	}
	return false
}

func (s *EcosystemService) ecosystemAudit(ctx context.Context, uid, projectID int64, action, resourceType, resourceID string, metadata map[string]any) {
	if s.repo == nil || projectID <= 0 || uid <= 0 {
		return
	}
	pid := projectID
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID: &pid, ActorUserID: uid, Action: action, ResourceType: resourceType,
		ResourceID: resourceID, Result: "SUCCESS", Metadata: safeAuditMetadata(metadata),
	})
}

func (s *EcosystemService) CreateServiceAccount(ctx context.Context, uid, projectID int64, name string, scopes []string, expiresAt *time.Time) (*model.ServiceAccountCredential, error) {
	if s.governance == nil {
		return nil, ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return nil, err
	}
	name = strings.TrimSpace(name)
	if name == "" || len([]rune(name)) > 120 {
		return nil, ErrInvalidInput
	}
	normalizedScopes, err := normalizeStringSet(scopes, serviceAccountScopes)
	if err != nil || len(normalizedScopes) == 0 {
		return nil, ErrInvalidInput
	}
	if expiresAt != nil {
		value := expiresAt.UTC()
		if !value.After(time.Now().UTC()) || value.After(time.Now().UTC().AddDate(2, 0, 0)) {
			return nil, ErrInvalidInput
		}
		expiresAt = &value
	}
	raw, prefix, err := createServiceAccountKey()
	if err != nil {
		return nil, err
	}
	item, err := s.repo.CreateServiceAccount(ctx, model.ServiceAccount{
		ProjectID: projectID, Name: name, KeyPrefix: prefix, Scopes: normalizedScopes,
		Status: "ACTIVE", CreatedBy: uid, ExpiresAt: expiresAt,
	}, serviceAccountSecretHash(raw))
	if err != nil {
		return nil, err
	}
	s.ecosystemAudit(ctx, uid, projectID, "service_account.create", "service_account", strconv.FormatInt(item.ID, 10), map[string]any{"name": name, "scopes": strings.Join(normalizedScopes, ",")})
	return &model.ServiceAccountCredential{ServiceAccount: *item, APIKey: raw}, nil
}

func (s *EcosystemService) ListServiceAccounts(ctx context.Context, uid, projectID int64) ([]model.ServiceAccount, error) {
	if s.governance == nil {
		return nil, ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return nil, err
	}
	return s.repo.ListServiceAccounts(ctx, projectID)
}

func (s *EcosystemService) RevokeServiceAccount(ctx context.Context, uid, projectID, id int64) error {
	if s.governance == nil {
		return ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return err
	}
	ok, err := s.repo.RevokeServiceAccount(ctx, projectID, id)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotFound
	}
	s.ecosystemAudit(ctx, uid, projectID, "service_account.revoke", "service_account", strconv.FormatInt(id, 10), nil)
	return nil
}

func (s *EcosystemService) AuthenticateServiceAccount(ctx context.Context, raw string) (*model.APIPrincipal, error) {
	prefix := parseServiceAccountPrefix(raw)
	if prefix == "" {
		return nil, ErrAPIKeyInvalid
	}
	item, expectedHash, err := s.repo.ServiceAccountByPrefix(ctx, prefix)
	if err != nil {
		return nil, err
	}
	if item == nil || item.Status != "ACTIVE" {
		return nil, ErrAPIKeyInvalid
	}
	actualHash := serviceAccountSecretHash(strings.TrimSpace(raw))
	if subtle.ConstantTimeCompare([]byte(actualHash), []byte(expectedHash)) != 1 {
		return nil, ErrAPIKeyInvalid
	}
	if item.ExpiresAt != nil && !item.ExpiresAt.After(time.Now().UTC()) {
		return nil, ErrAPIKeyInvalid
	}
	if s.governance == nil {
		return nil, ErrAPIKeyInvalid
	}
	if _, err := s.governance.RequireRole(ctx, item.CreatedBy, item.ProjectID, "DEVELOPER"); err != nil {
		return nil, ErrAPIKeyInvalid
	}
	_ = s.repo.TouchServiceAccount(ctx, item.ID)
	return &model.APIPrincipal{ServiceAccountID: item.ID, ProjectID: item.ProjectID, ActorUserID: item.CreatedBy, Scopes: item.Scopes}, nil
}

func (s *EcosystemService) RecordAPIUsage(ctx context.Context, principal *model.APIPrincipal, statusCode int, latencyMS int64) {
	if principal == nil {
		return
	}
	_ = s.repo.RecordAPIUsage(ctx, principal.ServiceAccountID, principal.ProjectID, statusCode, latencyMS)
}

type PublicRunInput struct {
	ConversationID *int64                `json:"conversationId,omitempty"`
	Task           string                `json:"task"`
	Scheduler      string                `json:"scheduler,omitempty"`
	Planner        string                `json:"planner,omitempty"`
	ExecutionMode  string                `json:"executionMode,omitempty"`
	SynthesisMode  string                `json:"synthesisMode,omitempty"`
	Constraints    model.TaskConstraints `json:"constraints,omitempty"`
}

func publicRequestHash(input PublicRunInput) string {
	raw, _ := json.Marshal(input)
	sum := sha256.Sum256(raw)
	return strings.ToUpper(hex.EncodeToString(sum[:]))
}

func (s *EcosystemService) checkPublicConversation(ctx context.Context, principal *model.APIPrincipal, conversationID int64) error {
	pid, err := s.repo.ProjectIDByConversation(ctx, principal.ActorUserID, conversationID)
	if errors.Is(err, repository.ErrNotOwned) {
		return ErrNotFound
	}
	if err != nil {
		return err
	}
	if pid == nil || *pid != principal.ProjectID {
		return ErrNotFound
	}
	return nil
}

func (s *EcosystemService) RunPublicTask(ctx context.Context, principal *model.APIPrincipal, input PublicRunInput, idempotencyKey string) (*RunTaskResult, bool, error) {
	if principal == nil || !hasScope(principal.Scopes, "tasks:write") {
		return nil, false, ErrAPIScopeDenied
	}
	input.Task = strings.TrimSpace(input.Task)
	if input.Task == "" || len([]rune(input.Task)) > 20000 {
		return nil, false, ErrInvalidInput
	}
	idempotencyKey = strings.TrimSpace(idempotencyKey)
	if len(idempotencyKey) > 160 {
		return nil, false, ErrInvalidInput
	}
	requestHash := publicRequestHash(input)
	reserved := false
	if idempotencyKey != "" {
		existing, err := s.repo.APIIdempotencyRecord(ctx, principal.ServiceAccountID, idempotencyKey)
		if err != nil {
			return nil, false, err
		}
		if existing != nil {
			if existing.RequestHash != requestHash {
				return nil, false, ErrIdempotencyConflict
			}
			if existing.Status == "COMPLETED" && len(existing.ResponseJSON) > 0 {
				var cached RunTaskResult
				if err := json.Unmarshal(existing.ResponseJSON, &cached); err != nil {
					return nil, false, err
				}
				return &cached, true, nil
			}
			return nil, false, ErrIdempotencyConflict
		}
		reserved, err = s.repo.ReserveAPIIdempotencyRecord(ctx, model.APIIdempotencyRecord{
			ServiceAccountID: principal.ServiceAccountID, IdempotencyKey: idempotencyKey,
			RequestHash: requestHash, Status: "IN_PROGRESS",
		})
		if err != nil {
			return nil, false, err
		}
		if !reserved {
			return nil, false, ErrIdempotencyConflict
		}
	}

	cleanupReservation := func() {
		if reserved {
			_ = s.repo.DeleteAPIIdempotencyReservation(ctx, principal.ServiceAccountID, idempotencyKey)
		}
	}

	conversationID := input.ConversationID
	if conversationID != nil {
		if err := s.checkPublicConversation(ctx, principal, *conversationID); err != nil {
			cleanupReservation()
			return nil, false, err
		}
	} else {
		if s.conversations == nil || s.projects == nil {
			cleanupReservation()
			return nil, false, errors.New("public api conversation service unavailable")
		}
		titleRunes := []rune(input.Task)
		if len(titleRunes) > 36 {
			titleRunes = titleRunes[:36]
		}
		conversation, err := s.conversations.Create(ctx, principal.ActorUserID, "API · "+string(titleRunes))
		if err != nil {
			cleanupReservation()
			return nil, false, err
		}
		if err := s.projects.AssignConversation(ctx, principal.ActorUserID, principal.ProjectID, conversation.ID); err != nil {
			_ = s.conversations.Delete(ctx, principal.ActorUserID, conversation.ID)
			cleanupReservation()
			return nil, false, err
		}
		conversationID = &conversation.ID
	}

	if s.tasks == nil {
		cleanupReservation()
		return nil, false, errors.New("public api task service unavailable")
	}
	result, err := s.tasks.Run(ctx, principal.ActorUserID, RunTaskInput{
		ConversationID: conversationID,
		Task:           input.Task, Scheduler: input.Scheduler, Planner: input.Planner,
		ExecutionMode: input.ExecutionMode, SynthesisMode: input.SynthesisMode,
		Constraints: input.Constraints,
	})
	if err != nil {
		cleanupReservation()
		return nil, false, err
	}
	if reserved {
		responseJSON, err := json.Marshal(result)
		if err != nil {
			cleanupReservation()
			return nil, false, err
		}
		if err := s.repo.CompleteAPIIdempotencyRecord(ctx, principal.ServiceAccountID, idempotencyKey, responseJSON); err != nil {
			return nil, false, err
		}
	}
	return result, false, nil
}

func (s *EcosystemService) PublicTask(ctx context.Context, principal *model.APIPrincipal, taskID int64) (*model.Task, error) {
	if principal == nil || !hasScope(principal.Scopes, "tasks:read") {
		return nil, ErrAPIScopeDenied
	}
	item, err := s.repo.TaskByID(ctx, principal.ActorUserID, taskID)
	if err != nil {
		return nil, err
	}
	if item == nil || item.ConversationID == nil {
		return nil, ErrNotFound
	}
	if err := s.checkPublicConversation(ctx, principal, *item.ConversationID); err != nil {
		return nil, err
	}
	return item, nil
}

var slugPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{2,79}$`)
var semverPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$`)

func normalizePackageKind(value string) string {
	value = strings.ToUpper(strings.TrimSpace(value))
	switch value {
	case "AGENT", "MCP", "PLUGIN":
		return value
	default:
		return ""
	}
}

func validateMarketplaceEndpoint(raw string, allowInternal bool) error {
	raw = strings.TrimSpace(raw)
	if allowInternal && strings.HasPrefix(raw, "internal://") {
		return nil
	}
	u, err := url.Parse(raw)
	if err != nil || strings.ToLower(u.Scheme) != "https" || u.Host == "" || u.User != nil {
		return ErrPackageValidation
	}
	host := strings.ToLower(strings.TrimSuffix(u.Hostname(), "."))
	if host == "" || host == "localhost" || strings.HasSuffix(host, ".localhost") || strings.HasSuffix(host, ".local") || strings.HasSuffix(host, ".internal") {
		return ErrPackageValidation
	}
	if ip := net.ParseIP(host); ip != nil {
		if ip.IsLoopback() || ip.IsPrivate() || ip.IsUnspecified() || ip.IsLinkLocalMulticast() || ip.IsLinkLocalUnicast() {
			return ErrPackageValidation
		}
	}
	return nil
}

func validateManifest(kind string, manifest model.EcosystemPackageManifest) (model.EcosystemPackageManifest, string, error) {
	manifest.SchemaVersion = strings.TrimSpace(manifest.SchemaVersion)
	if manifest.SchemaVersion == "" {
		manifest.SchemaVersion = "agentmesh.dev/v1"
	}
	manifest.Kind = normalizePackageKind(manifest.Kind)
	if manifest.Kind == "" {
		manifest.Kind = kind
	}
	if manifest.Kind != kind {
		return manifest, "", ErrPackageValidation
	}
	permissions, err := normalizeStringSet(manifest.Permissions, packagePermissions)
	if err != nil {
		return manifest, "", ErrPackageValidation
	}
	manifest.Permissions = permissions

	switch kind {
	case "AGENT":
		if manifest.Agent == nil || manifest.MCP != nil || manifest.Plugin != nil {
			return manifest, "", ErrPackageValidation
		}
		a := manifest.Agent
		a.Name = strings.TrimSpace(a.Name)
		a.Protocol = strings.ToLower(strings.TrimSpace(a.Protocol))
		if a.Protocol == "" {
			a.Protocol = "http"
		}
		if a.Name == "" || len(a.Capabilities) == 0 || (a.Protocol != "http" && a.Protocol != "a2a" && a.Protocol != "internal") {
			return manifest, "", ErrPackageValidation
		}
		if err := validateMarketplaceEndpoint(a.Endpoint, a.Protocol == "internal"); err != nil {
			return manifest, "", err
		}
	case "MCP":
		if manifest.MCP == nil || manifest.Agent != nil || manifest.Plugin != nil {
			return manifest, "", ErrPackageValidation
		}
		m := manifest.MCP
		m.Name = strings.TrimSpace(m.Name)
		if m.Transport == "" {
			m.Transport = "streamable_http"
		}
		if m.ConnectTimeoutMS <= 0 {
			m.ConnectTimeoutMS = 5000
		}
		if m.CallTimeoutMS <= 0 {
			m.CallTimeoutMS = 10000
		}
		if m.Name == "" || m.Transport != "streamable_http" || validateMarketplaceEndpoint(m.Endpoint, false) != nil {
			return manifest, "", ErrPackageValidation
		}
	case "PLUGIN":
		if manifest.Plugin == nil || manifest.Agent != nil || manifest.MCP != nil {
			return manifest, "", ErrPackageValidation
		}
		p := manifest.Plugin
		p.Name = strings.TrimSpace(p.Name)
		p.Runtime = strings.ToLower(strings.TrimSpace(p.Runtime))
		if p.Runtime == "" {
			p.Runtime = "registry"
		}
		if p.Name == "" || (p.Runtime != "registry" && p.Runtime != "remote" && p.Runtime != "builtin") {
			return manifest, "", ErrPackageValidation
		}
	}

	raw, err := json.Marshal(manifest)
	if err != nil || len(raw) > 128*1024 {
		return manifest, "", ErrPackageValidation
	}
	lower := strings.ToLower(string(raw))
	for _, forbidden := range []string{"api_key\"", "apikey\"", "access_token\"", "private_key\"", "password\"", "secret_value\""} {
		if strings.Contains(lower, forbidden) {
			return manifest, "", ErrPackageValidation
		}
	}
	sum := sha256.Sum256(raw)
	return manifest, strings.ToUpper(hex.EncodeToString(sum[:])), nil
}

type CreatePackageInput struct {
	Slug        string                         `json:"slug"`
	Name        string                         `json:"name"`
	Kind        string                         `json:"kind"`
	Summary     string                         `json:"summary"`
	Description string                         `json:"description"`
	Visibility  string                         `json:"visibility"`
	Version     string                         `json:"version"`
	Manifest    model.EcosystemPackageManifest `json:"manifest"`
	Publish     bool                           `json:"publish"`
}

func normalizeCreatePackageInput(input CreatePackageInput) (CreatePackageInput, string, error) {
	input.Slug = strings.ToLower(strings.TrimSpace(input.Slug))
	input.Name = strings.TrimSpace(input.Name)
	input.Kind = normalizePackageKind(input.Kind)
	input.Summary = strings.TrimSpace(input.Summary)
	input.Description = strings.TrimSpace(input.Description)
	input.Visibility = strings.ToUpper(strings.TrimSpace(input.Visibility))
	input.Version = strings.TrimPrefix(strings.TrimSpace(input.Version), "v")
	if input.Visibility == "" {
		input.Visibility = "PRIVATE"
	}
	if !slugPattern.MatchString(input.Slug) || input.Name == "" || input.Kind == "" || !semverPattern.MatchString(input.Version) || (input.Visibility != "PRIVATE" && input.Visibility != "PUBLIC") || (input.Publish && input.Visibility != "PUBLIC") {
		return input, "", ErrInvalidInput
	}
	if len([]rune(input.Name)) > 120 || len([]rune(input.Summary)) > 500 || len([]rune(input.Description)) > 12000 {
		return input, "", ErrInvalidInput
	}
	manifest, checksum, err := validateManifest(input.Kind, input.Manifest)
	if err != nil {
		return input, "", err
	}
	input.Manifest = manifest
	return input, checksum, nil
}

func (s *EcosystemService) CreatePackage(ctx context.Context, uid int64, input CreatePackageInput) (*model.EcosystemPackageDetail, error) {
	input, checksum, err := normalizeCreatePackageInput(input)
	if err != nil {
		return nil, err
	}
	existing, err := s.repo.EcosystemPackageBySlug(ctx, input.Slug)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, ErrAlreadyExists
	}
	pkg, err := s.repo.CreateEcosystemPackage(ctx, model.EcosystemPackage{
		OwnerUserID: uid, Slug: input.Slug, Name: input.Name, Kind: input.Kind,
		Summary: input.Summary, Description: input.Description, Visibility: input.Visibility, Status: "DRAFT",
	})
	if err != nil {
		return nil, err
	}
	version, err := s.repo.CreateEcosystemPackageVersion(ctx, model.EcosystemPackageVersion{
		PackageID: pkg.ID, Version: input.Version, Manifest: input.Manifest,
		Checksum: checksum, Status: "VALIDATED", CreatedBy: uid,
	})
	if err != nil {
		return nil, err
	}
	if input.Publish {
		if err := s.repo.PublishEcosystemPackage(ctx, pkg.ID, version.Version); err != nil {
			return nil, err
		}
		pkg, _ = s.repo.EcosystemPackageByID(ctx, pkg.ID)
	}
	return &model.EcosystemPackageDetail{Package: *pkg, Versions: []model.EcosystemPackageVersion{*version}}, nil
}

func (s *EcosystemService) AddPackageVersion(ctx context.Context, uid int64, slug, version string, manifest model.EcosystemPackageManifest) (*model.EcosystemPackageVersion, error) {
	pkg, err := s.repo.EcosystemPackageBySlug(ctx, strings.ToLower(strings.TrimSpace(slug)))
	if err != nil {
		return nil, err
	}
	if pkg == nil {
		return nil, ErrNotFound
	}
	if pkg.OwnerUserID != uid {
		return nil, ErrForbidden
	}
	version = strings.TrimPrefix(strings.TrimSpace(version), "v")
	if !semverPattern.MatchString(version) {
		return nil, ErrInvalidInput
	}
	existing, err := s.repo.EcosystemPackageVersion(ctx, pkg.ID, version)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, ErrAlreadyExists
	}
	normalized, checksum, err := validateManifest(pkg.Kind, manifest)
	if err != nil {
		return nil, err
	}
	return s.repo.CreateEcosystemPackageVersion(ctx, model.EcosystemPackageVersion{
		PackageID: pkg.ID, Version: version, Manifest: normalized, Checksum: checksum,
		Status: "VALIDATED", CreatedBy: uid,
	})
}

func (s *EcosystemService) PublishPackage(ctx context.Context, uid int64, slug, version string) (*model.EcosystemPackage, error) {
	pkg, err := s.repo.EcosystemPackageBySlug(ctx, strings.ToLower(strings.TrimSpace(slug)))
	if err != nil {
		return nil, err
	}
	if pkg == nil {
		return nil, ErrNotFound
	}
	if pkg.OwnerUserID != uid {
		return nil, ErrForbidden
	}
	version = strings.TrimPrefix(strings.TrimSpace(version), "v")
	item, err := s.repo.EcosystemPackageVersion(ctx, pkg.ID, version)
	if err != nil {
		return nil, err
	}
	if item == nil || item.Status != "VALIDATED" {
		return nil, ErrNotFound
	}
	if err := s.repo.PublishEcosystemPackage(ctx, pkg.ID, version); err != nil {
		return nil, err
	}
	return s.repo.EcosystemPackageByID(ctx, pkg.ID)
}

func (s *EcosystemService) SearchMarketplace(ctx context.Context, query, kind string, limit int) ([]model.EcosystemPackage, error) {
	kind = normalizePackageKind(kind)
	return s.repo.SearchEcosystemPackages(ctx, query, kind, nil, limit)
}

func (s *EcosystemService) SearchPackagesForUser(ctx context.Context, uid int64, query, kind string, limit int) ([]model.EcosystemPackage, error) {
	kind = normalizePackageKind(kind)
	return s.repo.SearchEcosystemPackages(ctx, query, kind, &uid, limit)
}

func (s *EcosystemService) PackageDetail(ctx context.Context, uid int64, slug string) (*model.EcosystemPackageDetail, error) {
	pkg, err := s.repo.EcosystemPackageBySlug(ctx, strings.ToLower(strings.TrimSpace(slug)))
	if err != nil {
		return nil, err
	}
	if pkg == nil || (pkg.Status != "PUBLISHED" && pkg.OwnerUserID != uid) {
		return nil, ErrNotFound
	}
	versions, err := s.repo.ListEcosystemPackageVersions(ctx, pkg.ID)
	if err != nil {
		return nil, err
	}
	return &model.EcosystemPackageDetail{Package: *pkg, Versions: versions}, nil
}

func (s *EcosystemService) PublicPackageDetail(ctx context.Context, slug string) (*model.EcosystemPackageDetail, error) {
	pkg, err := s.repo.EcosystemPackageBySlug(ctx, strings.ToLower(strings.TrimSpace(slug)))
	if err != nil {
		return nil, err
	}
	if pkg == nil || pkg.Status != "PUBLISHED" || pkg.Visibility != "PUBLIC" {
		return nil, ErrNotFound
	}
	versions, err := s.repo.ListEcosystemPackageVersions(ctx, pkg.ID)
	if err != nil {
		return nil, err
	}
	return &model.EcosystemPackageDetail{Package: *pkg, Versions: versions}, nil
}

func (s *EcosystemService) EcosystemOverview(ctx context.Context) (model.EcosystemOverview, error) {
	return s.repo.EcosystemOverview(ctx)
}

func packageRequiresAdmin(manifest model.EcosystemPackageManifest) bool {
	for _, permission := range manifest.Permissions {
		if permission == "network:outbound" || permission == "mcp:connect" {
			return true
		}
	}
	return false
}

func (s *EcosystemService) materializePackage(ctx context.Context, resourceOwnerID int64, version *model.EcosystemPackageVersion) (string, *int64, error) {
	if version == nil {
		return "", nil, ErrNotFound
	}
	switch version.Manifest.Kind {
	case "AGENT":
		if s.agents == nil || version.Manifest.Agent == nil {
			return "", nil, errors.New("agent marketplace service unavailable")
		}
		a := version.Manifest.Agent
		created, err := s.agents.Create(ctx, resourceOwnerID, model.Agent{
			Name: a.Name, Description: a.Description, Endpoint: a.Endpoint, Protocol: a.Protocol,
			Capabilities: a.Capabilities, Provider: a.Provider, ModelName: a.ModelName, Status: "ACTIVE",
		})
		if err != nil {
			return "", nil, err
		}
		id := created.ID
		return "AGENT", &id, nil
	case "MCP":
		if s.mcp == nil || version.Manifest.MCP == nil {
			return "", nil, errors.New("mcp marketplace service unavailable")
		}
		m := version.Manifest.MCP
		created, err := s.mcp.Create(ctx, resourceOwnerID, model.MCPServer{
			Name: m.Name, Transport: m.Transport, Endpoint: m.Endpoint, Enabled: true,
			ConnectTimeoutMS: m.ConnectTimeoutMS, CallTimeoutMS: m.CallTimeoutMS,
		})
		if err != nil {
			return "", nil, err
		}
		id := created.ID
		return "MCP", &id, nil
	case "PLUGIN":
		return "PLUGIN_REGISTRY", nil, nil
	default:
		return "", nil, ErrPackageValidation
	}
}

func (s *EcosystemService) removeMaterializedPackage(ctx context.Context, resourceOwnerID int64, installation *model.ProjectPackageInstallation) error {
	if installation == nil || installation.ResourceID == nil {
		return nil
	}
	switch installation.ResourceType {
	case "AGENT":
		if s.agents != nil {
			return s.agents.Delete(ctx, resourceOwnerID, *installation.ResourceID)
		}
	case "MCP":
		if s.mcp != nil {
			return s.mcp.Delete(ctx, resourceOwnerID, *installation.ResourceID)
		}
	}
	return nil
}

func (s *EcosystemService) InstallPackage(ctx context.Context, uid, projectID int64, slug, version string, config map[string]any) (*model.ProjectPackageInstallation, error) {
	if s.governance == nil {
		return nil, ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
		return nil, err
	}
	pkg, err := s.repo.EcosystemPackageBySlug(ctx, strings.ToLower(strings.TrimSpace(slug)))
	if err != nil {
		return nil, err
	}
	if pkg == nil || pkg.Status != "PUBLISHED" || pkg.Visibility != "PUBLIC" {
		return nil, ErrNotFound
	}
	version = strings.TrimPrefix(strings.TrimSpace(version), "v")
	if version == "" {
		version = pkg.LatestVersion
	}
	v, err := s.repo.EcosystemPackageVersion(ctx, pkg.ID, version)
	if err != nil {
		return nil, err
	}
	if v == nil || v.Status != "VALIDATED" {
		return nil, ErrNotFound
	}
	if packageRequiresAdmin(v.Manifest) {
		if _, err := s.governance.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
			return nil, err
		}
	}
	project, err := s.repo.ProjectByID(ctx, uid, projectID)
	if err != nil {
		return nil, err
	}
	if project == nil {
		return nil, ErrNotFound
	}
	existing, err := s.repo.ProjectPackageInstallationByPackage(ctx, projectID, pkg.ID)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		if err := s.removeMaterializedPackage(ctx, project.UserID, existing); err != nil && !errors.Is(err, ErrNotFound) {
			return nil, err
		}
	}
	resourceType, resourceID, err := s.materializePackage(ctx, project.UserID, v)
	if err != nil {
		return nil, err
	}
	if config == nil {
		config = map[string]any{}
	}
	item, err := s.repo.UpsertProjectPackageInstallation(ctx, model.ProjectPackageInstallation{
		ProjectID: projectID, PackageID: pkg.ID, VersionID: v.ID, Enabled: true,
		Config: config, ResourceType: resourceType, ResourceID: resourceID, InstalledBy: uid,
	})
	if err != nil {
		return nil, err
	}
	if existing == nil {
		_ = s.repo.IncrementEcosystemPackageInstallCount(ctx, pkg.ID)
	}
	s.ecosystemAudit(ctx, uid, projectID, "ecosystem.package.install", "ecosystem_package", strconv.FormatInt(pkg.ID, 10), map[string]any{"slug": pkg.Slug, "version": v.Version, "kind": pkg.Kind})
	return item, nil
}

func (s *EcosystemService) ListInstallations(ctx context.Context, uid, projectID int64) ([]model.ProjectPackageInstallation, error) {
	if s.governance == nil {
		return nil, ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "VIEWER"); err != nil {
		return nil, err
	}
	return s.repo.ListProjectPackageInstallations(ctx, projectID)
}

func (s *EcosystemService) SetInstallationEnabled(ctx context.Context, uid, projectID, installationID int64, enabled bool) (*model.ProjectPackageInstallation, error) {
	if s.governance == nil {
		return nil, ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
		return nil, err
	}
	installation, err := s.repo.ProjectPackageInstallationByID(ctx, projectID, installationID)
	if err != nil {
		return nil, err
	}
	if installation == nil {
		return nil, ErrNotFound
	}
	project, err := s.repo.ProjectByID(ctx, uid, projectID)
	if err != nil || project == nil {
		if err != nil {
			return nil, err
		}
		return nil, ErrNotFound
	}
	if installation.Enabled == enabled {
		return installation, nil
	}
	resourceType := installation.ResourceType
	resourceID := installation.ResourceID
	if !enabled {
		if err := s.removeMaterializedPackage(ctx, project.UserID, installation); err != nil && !errors.Is(err, ErrNotFound) {
			return nil, err
		}
		resourceID = nil
	} else {
		version, err := s.repo.EcosystemPackageVersionByID(ctx, installation.VersionID)
		if err != nil {
			return nil, err
		}
		resourceType, resourceID, err = s.materializePackage(ctx, project.UserID, version)
		if err != nil {
			return nil, err
		}
	}
	updated, err := s.repo.UpdateProjectPackageInstallationState(ctx, projectID, installationID, enabled, resourceType, resourceID)
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, ErrNotFound
	}
	s.ecosystemAudit(ctx, uid, projectID, "ecosystem.installation.toggle", "project_package_installation", strconv.FormatInt(installationID, 10), map[string]any{"enabled": enabled})
	return updated, nil
}

func (s *EcosystemService) DeleteInstallation(ctx context.Context, uid, projectID, installationID int64) error {
	if s.governance == nil {
		return ErrForbidden
	}
	if _, err := s.governance.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
		return err
	}
	installation, err := s.repo.ProjectPackageInstallationByID(ctx, projectID, installationID)
	if err != nil {
		return err
	}
	if installation == nil {
		return ErrNotFound
	}
	project, err := s.repo.ProjectByID(ctx, uid, projectID)
	if err != nil || project == nil {
		if err != nil {
			return err
		}
		return ErrNotFound
	}
	if err := s.removeMaterializedPackage(ctx, project.UserID, installation); err != nil && !errors.Is(err, ErrNotFound) {
		return err
	}
	ok, err := s.repo.DeleteProjectPackageInstallation(ctx, projectID, installationID)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotFound
	}
	s.ecosystemAudit(ctx, uid, projectID, "ecosystem.package.uninstall", "project_package_installation", strconv.FormatInt(installationID, 10), nil)
	return nil
}

func (s *EcosystemService) ExportPackage(ctx context.Context, uid int64, slug, version string) (*model.EcosystemPackageBundle, error) {
	detail, err := s.PackageDetail(ctx, uid, slug)
	if err != nil {
		return nil, err
	}
	pkg := detail.Package
	if version == "" {
		version = pkg.LatestVersion
		if version == "" && len(detail.Versions) > 0 {
			version = detail.Versions[0].Version
		}
	}
	var selected *model.EcosystemPackageVersion
	for i := range detail.Versions {
		if detail.Versions[i].Version == version {
			selected = &detail.Versions[i]
			break
		}
	}
	if selected == nil {
		return nil, ErrNotFound
	}
	return &model.EcosystemPackageBundle{FormatVersion: "agentmesh.bundle/v1", Package: pkg, Version: *selected}, nil
}

func (s *EcosystemService) ImportPackage(ctx context.Context, uid int64, bundle model.EcosystemPackageBundle) (*model.EcosystemPackageDetail, error) {
	if bundle.FormatVersion != "agentmesh.bundle/v1" {
		return nil, ErrInvalidInput
	}
	input := CreatePackageInput{
		Slug: bundle.Package.Slug, Name: bundle.Package.Name, Kind: bundle.Package.Kind,
		Summary: bundle.Package.Summary, Description: bundle.Package.Description,
		Visibility: "PRIVATE", Version: bundle.Version.Version, Manifest: bundle.Version.Manifest,
		Publish: false,
	}
	return s.CreatePackage(ctx, uid, input)
}

func (s *EcosystemService) DescribePackageValidation(kind string, manifest model.EcosystemPackageManifest) (map[string]any, error) {
	kind = normalizePackageKind(kind)
	if kind == "" {
		return nil, ErrInvalidInput
	}
	normalized, checksum, err := validateManifest(kind, manifest)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"valid": true, "kind": kind, "schemaVersion": normalized.SchemaVersion,
		"permissions": normalized.Permissions, "checksum": checksum,
	}, nil
}

func (s *EcosystemService) PublicMarketplaceForPrincipal(ctx context.Context, principal *model.APIPrincipal, query, kind string, limit int) ([]model.EcosystemPackage, error) {
	if principal == nil || (!hasScope(principal.Scopes, "marketplace:read") && !hasScope(principal.Scopes, "ecosystem:read")) {
		return nil, ErrAPIScopeDenied
	}
	return s.SearchMarketplace(ctx, query, kind, limit)
}

func (s *EcosystemService) PublicPackageForPrincipal(ctx context.Context, principal *model.APIPrincipal, slug string) (*model.EcosystemPackageDetail, error) {
	if principal == nil || (!hasScope(principal.Scopes, "marketplace:read") && !hasScope(principal.Scopes, "ecosystem:read")) {
		return nil, ErrAPIScopeDenied
	}
	return s.PublicPackageDetail(ctx, slug)
}

func (s *EcosystemService) DebugAPIPrincipal(principal *model.APIPrincipal) string {
	if principal == nil {
		return ""
	}
	return fmt.Sprintf("service-account:%d project:%d", principal.ServiceAccountID, principal.ProjectID)
}

// Compile-time check that the concrete MySQL repository still satisfies the
// V4 contract. This catches accidental repository/API drift during future
// migrations without coupling the service implementation to MySQL at runtime.
var _ ecosystemRepository = (*repository.MySQL)(nil)
