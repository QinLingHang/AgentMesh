package service

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"strconv"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

var ErrForbidden = errors.New("forbidden")
var ErrQuotaExceeded = errors.New("quota exceeded")
var ErrModelProviderNotConfigured = errors.New("model provider not configured")
var ErrModelAutoRouteNotConfigured = errors.New("model auto route not configured")
var ErrProjectAlreadyBound = errors.New("project already bound to another organization")

type governanceRepository interface {
	ProjectRole(context.Context, int64, int64) (string, error)
	ListProjectMembers(context.Context, int64) ([]model.ProjectMember, error)
	UpsertProjectMemberByEmail(context.Context, int64, string, string) (*model.ProjectMember, error)
	DeleteProjectMember(context.Context, int64, int64) (bool, error)
	GetProjectQuota(context.Context, int64) (model.ProjectQuota, error)
	UpsertProjectQuota(context.Context, model.ProjectQuota) (model.ProjectQuota, error)
	GetProjectUsage(context.Context, int64) (model.ProjectUsage, error)
	ConsumeProjectRequest(context.Context, int64, int64) (bool, error)
	DailyToolActions(context.Context, int64) (int64, error)
	RecordProjectUsage(context.Context, int64, int64, float64, int64) error
	CreateProjectSecret(context.Context, model.ProjectSecret, []byte, []byte) (*model.ProjectSecret, error)
	ListProjectSecrets(context.Context, int64) ([]model.ProjectSecret, error)
	SecretCiphertext(context.Context, int64, int64) ([]byte, []byte, error)
	DeleteProjectSecret(context.Context, int64, int64) (bool, error)
	UpsertProjectModelProvider(context.Context, model.ProjectModelProvider) (*model.ProjectModelProvider, error)
	GetProjectModelProvider(context.Context, int64) (*model.ProjectModelProvider, error)
	AppendAudit(context.Context, model.AuditEvent) error
	ListAudit(context.Context, int64, int) ([]model.AuditEvent, error)
	RecordRunCost(context.Context, model.RunCostRecord) error
	RunCostByTask(context.Context, int64, int64) (*model.RunCostRecord, error)
	CostSummary(context.Context, int64, *int64, model.CostQuery) (model.CostSummary, error)
	CreateOrganization(context.Context, int64, string) (*model.Organization, error)
	ListOrganizations(context.Context, int64) ([]model.Organization, error)
	OrganizationRole(context.Context, int64, int64) (string, error)
	UpsertOrganizationMemberByEmail(context.Context, int64, string, string) (*model.OrganizationMember, error)
	BindProjectToOrganization(context.Context, int64, int64, int64) error
	GetUserModelProvider(context.Context, int64) (*model.UserModelProvider, error)
	UserModelProviderCiphertext(context.Context, int64) ([]byte, []byte, error)
	UpsertUserModelProvider(context.Context, model.UserModelProvider, []byte, []byte) (*model.UserModelProvider, error)
	DeleteUserModelProvider(context.Context, int64) (bool, error)
	ListUserModelServices(context.Context, int64) ([]model.UserModelService, error)
	UserModelServiceByID(context.Context, int64, int64) (*model.UserModelService, error)
	UserModelServiceCiphertext(context.Context, int64, int64) ([]byte, []byte, error)
	CreateUserModelService(context.Context, model.UserModelService, []byte, []byte) (*model.UserModelService, error)
	UpdateUserModelService(context.Context, model.UserModelService, []byte, []byte) (*model.UserModelService, error)
	DeleteUserModelService(context.Context, int64, int64) (bool, error)
	ClearUserModelDefault(context.Context, int64, int64) error
	SetFirstUserModelServiceDefault(context.Context, int64) error
	DeleteAllUserModelServices(context.Context, int64) (int64, error)
}

type GovernanceService struct {
	repo governanceRepository
	aead cipher.AEAD
}

func NewGovernanceService(repo governanceRepository, masterKey string) (*GovernanceService, error) {
	if strings.TrimSpace(masterKey) == "" {
		return nil, errors.New("governance master key is required")
	}
	h := sha256.Sum256([]byte(masterKey))
	block, err := aes.NewCipher(h[:])
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &GovernanceService{repo: repo, aead: aead}, nil
}

func roleRank(role string) int {
	switch strings.ToUpper(role) {
	case "OWNER":
		return 4
	case "ADMIN":
		return 3
	case "DEVELOPER":
		return 2
	case "VIEWER":
		return 1
	default:
		return 0
	}
}
func validAssignableRole(role string) bool {
	role = strings.ToUpper(strings.TrimSpace(role))
	return role == "ADMIN" || role == "DEVELOPER" || role == "VIEWER"
}

func (s *GovernanceService) RequireRole(ctx context.Context, uid, projectID int64, minRole string) (string, error) {
	if uid <= 0 || projectID <= 0 {
		return "", ErrInvalidInput
	}
	role, err := s.repo.ProjectRole(ctx, uid, projectID)
	if err != nil {
		return "", err
	}
	if role == "" {
		return "", ErrNotFound
	}
	if roleRank(role) < roleRank(minRole) {
		return role, ErrForbidden
	}
	return role, nil
}

func safeAuditMetadata(input map[string]any) map[string]any {
	if len(input) == 0 {
		return nil
	}
	out := map[string]any{}
	for k, v := range input {
		lk := strings.ToLower(k)
		if strings.Contains(lk, "secret") || strings.Contains(lk, "token") || strings.Contains(lk, "password") || strings.Contains(lk, "key") || strings.Contains(lk, "credential") || strings.Contains(lk, "otp") {
			out[k] = "[REDACTED]"
			continue
		}
		switch x := v.(type) {
		case string:
			if len(x) > 160 {
				out[k] = x[:160] + "…"
			} else {
				out[k] = x
			}
		case bool, float64, int, int64:
			out[k] = v
		default:
			out[k] = fmt.Sprint(v)
		}
	}
	return out
}
func (s *GovernanceService) audit(ctx context.Context, uid, projectID int64, action, resType, resID, result string, meta map[string]any) {
	pid := projectID
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{ProjectID: &pid, ActorUserID: uid, Action: action, ResourceType: resType, ResourceID: resID, Result: result, Metadata: safeAuditMetadata(meta)})
}

func (s *GovernanceService) Overview(ctx context.Context, uid, projectID int64) (model.GovernanceOverview, error) {
	role, err := s.RequireRole(ctx, uid, projectID, "VIEWER")
	if err != nil {
		return model.GovernanceOverview{}, err
	}
	members, err := s.repo.ListProjectMembers(ctx, projectID)
	if err != nil {
		return model.GovernanceOverview{}, err
	}
	quota, err := s.repo.GetProjectQuota(ctx, projectID)
	if err != nil {
		return model.GovernanceOverview{}, err
	}
	usage, err := s.repo.GetProjectUsage(ctx, projectID)
	if err != nil {
		return model.GovernanceOverview{}, err
	}
	secrets := []model.ProjectSecret{}
	if roleRank(role) >= roleRank("ADMIN") {
		secrets, _ = s.repo.ListProjectSecrets(ctx, projectID)
	}
	provider, err := s.repo.GetProjectModelProvider(ctx, projectID)
	if err != nil {
		return model.GovernanceOverview{}, err
	}
	audit := []model.AuditEvent{}
	if roleRank(role) >= roleRank("ADMIN") {
		audit, _ = s.repo.ListAudit(ctx, projectID, 100)
	}
	return model.GovernanceOverview{Role: role, Members: members, Quota: quota, Usage: usage, Secrets: secrets, ModelProvider: provider, Audit: audit}, nil
}

func (s *GovernanceService) AddMember(ctx context.Context, uid, projectID int64, email, role string) (*model.ProjectMember, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return nil, err
	}
	email = strings.ToLower(strings.TrimSpace(email))
	role = strings.ToUpper(strings.TrimSpace(role))
	if email == "" || !validAssignableRole(role) {
		return nil, ErrInvalidInput
	}
	item, err := s.repo.UpsertProjectMemberByEmail(ctx, projectID, email, role)
	if err != nil {
		return nil, err
	}
	if item == nil {
		return nil, ErrNotFound
	}
	s.audit(ctx, uid, projectID, "project.member.upsert", "project_member", strconv.FormatInt(item.UserID, 10), "SUCCESS", map[string]any{"role": role, "email": email})
	return item, nil
}
func (s *GovernanceService) RemoveMember(ctx context.Context, uid, projectID, memberUID int64) error {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return err
	}
	if memberUID <= 0 || memberUID == uid {
		return ErrInvalidInput
	}
	ok, err := s.repo.DeleteProjectMember(ctx, projectID, memberUID)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotFound
	}
	s.audit(ctx, uid, projectID, "project.member.delete", "project_member", strconv.FormatInt(memberUID, 10), "SUCCESS", nil)
	return nil
}
func (s *GovernanceService) UpdateQuota(ctx context.Context, uid, projectID int64, q model.ProjectQuota) (model.ProjectQuota, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return model.ProjectQuota{}, err
	}
	if q.RequestsPerMinute <= 0 || q.ConcurrentTasks <= 0 || q.MonthlyTokenLimit < 0 || q.MonthlyCostLimit < 0 || q.DailyToolActionLimit < 0 {
		return model.ProjectQuota{}, ErrInvalidInput
	}
	q.ProjectID = projectID
	out, err := s.repo.UpsertProjectQuota(ctx, q)
	if err == nil {
		s.audit(ctx, uid, projectID, "project.quota.update", "project_quota", strconv.FormatInt(projectID, 10), "SUCCESS", map[string]any{"requestsPerMinute": q.RequestsPerMinute, "concurrentTasks": q.ConcurrentTasks, "monthlyTokenLimit": q.MonthlyTokenLimit, "monthlyCostLimit": q.MonthlyCostLimit, "dailyToolActionLimit": q.DailyToolActionLimit})
	}
	return out, err
}

func maskHint(value string) string {
	r := []rune(strings.TrimSpace(value))
	if len(r) == 0 {
		return ""
	}
	if len(r) <= 4 {
		return "••••"
	}
	tail := string(r[len(r)-4:])
	return "••••" + tail
}
func (s *GovernanceService) CreateSecret(ctx context.Context, uid, projectID int64, name, kind, value string) (*model.ProjectSecret, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return nil, err
	}
	name = strings.TrimSpace(name)
	kind = strings.ToUpper(strings.TrimSpace(kind))
	value = strings.TrimSpace(value)
	if name == "" || len(name) > 100 || kind == "" || value == "" || len(value) > 16000 {
		return nil, ErrInvalidInput
	}
	nonce := make([]byte, s.aead.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	aad := []byte(fmt.Sprintf("agentmesh:project:%d:secret:%s", projectID, name))
	ciphertext := s.aead.Seal(nil, nonce, []byte(value), aad)
	item := model.ProjectSecret{ProjectID: projectID, Name: name, Kind: kind, MaskedHint: maskHint(value), CreatedBy: uid}
	saved, err := s.repo.CreateProjectSecret(ctx, item, ciphertext, nonce)
	if err == nil {
		s.audit(ctx, uid, projectID, "project.secret.create", "project_secret", saved.Name, "SUCCESS", map[string]any{"kind": kind, "value": "[REDACTED]"})
	}
	return saved, err
}
func (s *GovernanceService) ResolveSecret(ctx context.Context, uid, projectID, secretID int64) (string, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
		return "", err
	}
	c, n, err := s.repo.SecretCiphertext(ctx, projectID, secretID)
	if err != nil {
		return "", err
	}
	if len(c) == 0 {
		return "", ErrNotFound
	}
	items, err := s.repo.ListProjectSecrets(ctx, projectID)
	if err != nil {
		return "", err
	}
	name := ""
	for _, it := range items {
		if it.ID == secretID {
			name = it.Name
			break
		}
	}
	if name == "" {
		return "", ErrNotFound
	}
	plain, err := s.aead.Open(nil, n, c, []byte(fmt.Sprintf("agentmesh:project:%d:secret:%s", projectID, name)))
	if err != nil {
		return "", errors.New("secret decryption failed")
	}
	return string(plain), nil
}
func (s *GovernanceService) DeleteSecret(ctx context.Context, uid, projectID, id int64) error {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return err
	}
	ok, err := s.repo.DeleteProjectSecret(ctx, projectID, id)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotFound
	}
	s.audit(ctx, uid, projectID, "project.secret.delete", "project_secret", strconv.FormatInt(id, 10), "SUCCESS", nil)
	return nil
}

func validateProviderURL(raw string) error {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || u.Scheme != "https" || u.Hostname() == "" {
		return ErrInvalidInput
	}
	host := strings.ToLower(u.Hostname())
	if host == "localhost" || strings.HasSuffix(host, ".localhost") {
		return ErrInvalidInput
	}
	if ip := net.ParseIP(host); ip != nil {
		if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified() {
			return ErrInvalidInput
		}
	}
	return nil
}
func (s *GovernanceService) UpsertProvider(ctx context.Context, uid, projectID int64, p model.ProjectModelProvider) (*model.ProjectModelProvider, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return nil, err
	}
	p.ProjectID = projectID
	p.Provider = strings.TrimSpace(p.Provider)
	p.ModelName = strings.TrimSpace(p.ModelName)
	p.BaseURL = strings.TrimRight(strings.TrimSpace(p.BaseURL), "/")
	if p.Provider == "" || p.ModelName == "" || validateProviderURL(p.BaseURL) != nil {
		return nil, ErrInvalidInput
	}
	if p.SecretID != nil {
		if _, err := s.ResolveSecret(ctx, uid, projectID, *p.SecretID); err != nil {
			return nil, err
		}
	}
	saved, err := s.repo.UpsertProjectModelProvider(ctx, p)
	if err == nil {
		s.audit(ctx, uid, projectID, "project.model_provider.upsert", "project_model_provider", strconv.FormatInt(projectID, 10), "SUCCESS", map[string]any{"provider": p.Provider, "baseUrl": p.BaseURL, "modelName": p.ModelName, "secretId": p.SecretID})
	}
	return saved, err
}

func (s *GovernanceService) Audit(ctx context.Context, uid, projectID int64, limit int) ([]model.AuditEvent, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "ADMIN"); err != nil {
		return nil, err
	}
	return s.repo.ListAudit(ctx, projectID, limit)
}
func (s *GovernanceService) CheckQuota(ctx context.Context, uid, projectID int64) error {
	if _, err := s.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
		return err
	}
	q, err := s.repo.GetProjectQuota(ctx, projectID)
	if err != nil {
		return err
	}
	u, err := s.repo.GetProjectUsage(ctx, projectID)
	if err != nil {
		return err
	}
	dailyToolActions, err := s.repo.DailyToolActions(ctx, projectID)
	if err != nil {
		return err
	}
	if u.ConcurrentTasks >= q.ConcurrentTasks ||
		u.TokenCount >= q.MonthlyTokenLimit ||
		u.EstimatedCost >= q.MonthlyCostLimit ||
		dailyToolActions >= q.DailyToolActionLimit {
		return ErrQuotaExceeded
	}
	allowed, err := s.repo.ConsumeProjectRequest(ctx, projectID, q.RequestsPerMinute)
	if err != nil {
		return err
	}
	if !allowed {
		return ErrQuotaExceeded
	}
	return nil
}

func (s *GovernanceService) RecordUsage(ctx context.Context, projectID, tokens int64, cost float64, toolActions int64) {
	if projectID <= 0 || tokens < 0 || cost < 0 || toolActions < 0 {
		return
	}
	_ = s.repo.RecordProjectUsage(ctx, projectID, tokens, cost, toolActions)
}

func (s *GovernanceService) RecordRunCost(ctx context.Context, record model.RunCostRecord) {
	if record.TaskID <= 0 || record.UserID <= 0 {
		return
	}
	if record.CostStatus == "" {
		if record.EstimatedCost > 0 {
			record.CostStatus = "estimated"
		} else {
			record.CostStatus = "unavailable"
		}
	}
	_ = s.repo.RecordRunCost(ctx, record)
}

func (s *GovernanceService) RunCost(ctx context.Context, uid, taskID int64) (*model.RunCostRecord, error) {
	if uid <= 0 || taskID <= 0 {
		return nil, ErrInvalidInput
	}
	item, err := s.repo.RunCostByTask(ctx, uid, taskID)
	if err != nil {
		return nil, err
	}
	if item == nil {
		return nil, ErrNotFound
	}
	return item, nil
}

func (s *GovernanceService) CostSummary(
	ctx context.Context,
	uid int64,
	projectID *int64,
	query model.CostQuery,
) (model.CostSummary, error) {
	if uid <= 0 {
		return model.CostSummary{}, ErrInvalidInput
	}
	query.Provider = strings.TrimSpace(query.Provider)
	query.ModelName = strings.TrimSpace(query.ModelName)
	if len(query.Provider) > 64 || len(query.ModelName) > 191 {
		return model.CostSummary{}, ErrInvalidInput
	}
	if query.From != nil && query.To != nil && !query.From.Before(*query.To) {
		return model.CostSummary{}, ErrInvalidInput
	}
	if projectID != nil {
		if *projectID <= 0 {
			return model.CostSummary{}, ErrInvalidInput
		}
		if _, err := s.RequireRole(ctx, uid, *projectID, "VIEWER"); err != nil {
			return model.CostSummary{}, err
		}
	}
	return s.repo.CostSummary(ctx, uid, projectID, query)
}

func secretFingerprint(value string) string {
	h := sha256.Sum256([]byte(value))
	return hex.EncodeToString(h[:8])
}

func (s *GovernanceService) ResolveProjectModelRuntime(ctx context.Context, uid, projectID int64) (*runtimeclient.ProjectModelRuntime, error) {
	if _, err := s.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
		return nil, err
	}
	p, err := s.repo.GetProjectModelProvider(ctx, projectID)
	if err != nil || p == nil || !p.Enabled {
		return nil, err
	}
	if p.SecretID == nil {
		return nil, ErrInvalidInput
	}
	key, err := s.ResolveSecret(ctx, uid, projectID, *p.SecretID)
	if err != nil {
		return nil, err
	}
	return &runtimeclient.ProjectModelRuntime{Provider: p.Provider, BaseURL: p.BaseURL, ModelName: p.ModelName, APIKey: key}, nil
}

func userModelAAD(uid int64) []byte {
	return []byte(fmt.Sprintf("agentmesh:user:%d:model-provider", uid))
}

func userModelServiceAAD(uid int64, serviceKey string) []byte {
	return []byte(fmt.Sprintf("agentmesh:user:%d:model-service:%s", uid, serviceKey))
}

func newUserModelServiceKey() (string, error) {
	value := make([]byte, 16)
	if _, err := io.ReadFull(rand.Reader, value); err != nil {
		return "", err
	}
	encoded := hex.EncodeToString(value)
	return fmt.Sprintf("%s-%s-%s-%s-%s", encoded[:8], encoded[8:12], encoded[12:16], encoded[16:20], encoded[20:]), nil
}

func userModelServiceName(provider string) string {
	switch strings.ToLower(strings.TrimSpace(provider)) {
	case "qwen":
		return "我的通义千问"
	case "openai", "openai-compatible", "openai_compatible":
		return "我的 OpenAI"
	default:
		return "默认模型服务"
	}
}

func normalizeModelSelection(selection model.ModelSelection) (model.ModelSelection, error) {
	selection.Mode = strings.ToLower(strings.TrimSpace(selection.Mode))
	if selection.Mode == "" {
		selection.Mode = "auto"
	}
	switch selection.Mode {
	case "auto":
		selection.ServiceID = nil
		return selection, nil
	case "manual":
		if selection.ServiceID == nil || *selection.ServiceID <= 0 {
			return model.ModelSelection{}, ErrInvalidInput
		}
		return selection, nil
	default:
		return model.ModelSelection{}, ErrInvalidInput
	}
}

func normalizeUserModelServiceInput(input model.UserModelServiceInput) (model.UserModelServiceInput, error) {
	input.Name = strings.TrimSpace(input.Name)
	input.Provider = strings.TrimSpace(input.Provider)
	input.BaseURL = strings.TrimRight(strings.TrimSpace(input.BaseURL), "/")
	input.ModelName = strings.TrimSpace(input.ModelName)
	input.VisionModelName = strings.TrimSpace(input.VisionModelName)
	input.APIKey = strings.TrimSpace(input.APIKey)

	if input.Name == "" || len(input.Name) > 120 ||
		input.Provider == "" || len(input.Provider) > 40 ||
		input.ModelName == "" || len(input.ModelName) > 120 ||
		len(input.VisionModelName) > 120 || validateProviderURL(input.BaseURL) != nil ||
		len(input.APIKey) > 16000 {
		return model.UserModelServiceInput{}, ErrInvalidInput
	}
	return input, nil
}

func (s *GovernanceService) encryptUserModelServiceKey(uid int64, serviceKey, apiKey string) ([]byte, []byte, string, error) {
	if strings.TrimSpace(apiKey) == "" {
		return nil, nil, "", ErrInvalidInput
	}
	nonce := make([]byte, s.aead.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, nil, "", err
	}
	plain := []byte(strings.TrimSpace(apiKey))
	ciphertext := s.aead.Seal(nil, nonce, plain, userModelServiceAAD(uid, serviceKey))
	return ciphertext, nonce, maskHint(string(plain)), nil
}

func (s *GovernanceService) decryptUserModelServiceKey(ctx context.Context, uid int64, item model.UserModelService) (string, error) {
	ciphertext, nonce, err := s.repo.UserModelServiceCiphertext(ctx, uid, item.ID)
	if err != nil {
		return "", err
	}
	if len(ciphertext) == 0 || len(nonce) == 0 {
		return "", ErrModelProviderNotConfigured
	}
	plain, err := s.aead.Open(nil, nonce, ciphertext, userModelServiceAAD(uid, item.ServiceKey))
	if err != nil {
		return "", errors.New("user model service secret decryption failed")
	}
	return string(plain), nil
}

// ensureUserModelServices performs a one-time, request-safe migration from the
// legacy single-provider row into the multi-service pool. The compatibility
// HTTP contract is served from the pool afterwards, so the old encrypted row
// is removed and cannot resurrect a deliberately deleted final service.
func (s *GovernanceService) ensureUserModelServices(ctx context.Context, uid int64) ([]model.UserModelService, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}
	items, err := s.repo.ListUserModelServices(ctx, uid)
	if err != nil || len(items) > 0 {
		return items, err
	}

	legacy, err := s.repo.GetUserModelProvider(ctx, uid)
	if err != nil || legacy == nil {
		return items, err
	}
	ciphertext, nonce, err := s.repo.UserModelProviderCiphertext(ctx, uid)
	if err != nil {
		return nil, err
	}
	if len(ciphertext) == 0 || len(nonce) == 0 {
		return items, nil
	}
	plain, err := s.aead.Open(nil, nonce, ciphertext, userModelAAD(uid))
	if err != nil {
		return nil, errors.New("legacy user model secret decryption failed")
	}

	serviceKey := fmt.Sprintf("legacy-%d", uid)
	newCiphertext, newNonce, masked, err := s.encryptUserModelServiceKey(uid, serviceKey, string(plain))
	if err != nil {
		return nil, err
	}
	created, err := s.repo.CreateUserModelService(ctx, model.UserModelService{
		ServiceKey:      serviceKey,
		UserID:          uid,
		Name:            userModelServiceName(legacy.Provider),
		Provider:        legacy.Provider,
		BaseURL:         legacy.BaseURL,
		ModelName:       legacy.ModelName,
		VisionModelName: legacy.VisionModelName,
		MaskedHint:      masked,
		Enabled:         legacy.Enabled,
		AutoRoute:       true,
		IsDefault:       true,
	}, newCiphertext, newNonce)
	if err != nil {
		// A concurrent request may have completed the same migration. Re-read the
		// pool before surfacing a failure.
		items, readErr := s.repo.ListUserModelServices(ctx, uid)
		if readErr == nil && len(items) > 0 {
			return items, nil
		}
		return nil, err
	}

	// The compatibility HTTP contract now reads from user_model_services, so the
	// legacy row must be removed after a successful migration. Keeping it would
	// resurrect a deliberately deleted last service on the next list request.
	legacyDeleted, deleteErr := s.repo.DeleteUserModelProvider(ctx, uid)
	if deleteErr != nil || !legacyDeleted {
		if created != nil {
			_, _ = s.repo.DeleteUserModelService(ctx, uid, created.ID)
		}
		if deleteErr != nil {
			return nil, deleteErr
		}
		return nil, errors.New("legacy user model migration cleanup failed")
	}

	return s.repo.ListUserModelServices(ctx, uid)
}

func (s *GovernanceService) ListUserModelServices(ctx context.Context, uid int64) ([]model.UserModelService, error) {
	return s.ensureUserModelServices(ctx, uid)
}

func (s *GovernanceService) CreateUserModelService(ctx context.Context, uid int64, input model.UserModelServiceInput) (*model.UserModelService, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}
	input, err := normalizeUserModelServiceInput(input)
	if err != nil || input.APIKey == "" {
		return nil, ErrInvalidInput
	}
	existing, err := s.ensureUserModelServices(ctx, uid)
	if err != nil {
		return nil, err
	}
	serviceKey, err := newUserModelServiceKey()
	if err != nil {
		return nil, err
	}
	ciphertext, nonce, masked, err := s.encryptUserModelServiceKey(uid, serviceKey, input.APIKey)
	if err != nil {
		return nil, err
	}
	makeDefault := input.Enabled && (input.IsDefault || len(existing) == 0)
	if makeDefault {
		if err := s.repo.ClearUserModelDefault(ctx, uid, 0); err != nil {
			return nil, err
		}
	}
	item, err := s.repo.CreateUserModelService(ctx, model.UserModelService{
		ServiceKey:      serviceKey,
		UserID:          uid,
		Name:            input.Name,
		Provider:        input.Provider,
		BaseURL:         input.BaseURL,
		ModelName:       input.ModelName,
		VisionModelName: input.VisionModelName,
		MaskedHint:      masked,
		Enabled:         input.Enabled,
		AutoRoute:       input.AutoRoute,
		IsDefault:       makeDefault,
	}, ciphertext, nonce)
	if err != nil {
		return nil, err
	}
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID: nil, ActorUserID: uid, Action: "user.model_service.create",
		ResourceType: "user_model_service", ResourceID: strconv.FormatInt(item.ID, 10), Result: "SUCCESS",
		Metadata: safeAuditMetadata(map[string]any{
			"name": item.Name, "provider": item.Provider, "baseUrl": item.BaseURL,
			"modelName": item.ModelName, "visionModelName": item.VisionModelName,
			"autoRoute": item.AutoRoute, "isDefault": item.IsDefault, "apiKey": "[REDACTED]",
		}),
	})
	return item, nil
}

func (s *GovernanceService) UpdateUserModelService(ctx context.Context, uid, id int64, input model.UserModelServiceInput) (*model.UserModelService, error) {
	if uid <= 0 || id <= 0 {
		return nil, ErrInvalidInput
	}
	input, err := normalizeUserModelServiceInput(input)
	if err != nil {
		return nil, err
	}
	if _, err := s.ensureUserModelServices(ctx, uid); err != nil {
		return nil, err
	}
	existing, err := s.repo.UserModelServiceByID(ctx, uid, id)
	if err != nil {
		return nil, err
	}
	if existing == nil {
		return nil, ErrNotFound
	}

	ciphertext, nonce, err := s.repo.UserModelServiceCiphertext(ctx, uid, id)
	if err != nil {
		return nil, err
	}
	masked := existing.MaskedHint
	if input.APIKey != "" {
		ciphertext, nonce, masked, err = s.encryptUserModelServiceKey(uid, existing.ServiceKey, input.APIKey)
		if err != nil {
			return nil, err
		}
	}
	if len(ciphertext) == 0 || len(nonce) == 0 {
		return nil, ErrInvalidInput
	}

	item := *existing
	item.Name = input.Name
	item.Provider = input.Provider
	item.BaseURL = input.BaseURL
	item.ModelName = input.ModelName
	item.VisionModelName = input.VisionModelName
	item.MaskedHint = masked
	item.Enabled = input.Enabled
	item.AutoRoute = input.AutoRoute
	item.IsDefault = input.IsDefault && input.Enabled

	saved, err := s.repo.UpdateUserModelService(ctx, item, ciphertext, nonce)
	if err != nil {
		return nil, err
	}
	if saved == nil {
		return nil, ErrNotFound
	}
	if saved.IsDefault {
		if err := s.repo.ClearUserModelDefault(ctx, uid, saved.ID); err != nil {
			return nil, err
		}
	}
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID: nil, ActorUserID: uid, Action: "user.model_service.update",
		ResourceType: "user_model_service", ResourceID: strconv.FormatInt(saved.ID, 10), Result: "SUCCESS",
		Metadata: safeAuditMetadata(map[string]any{
			"name": saved.Name, "provider": saved.Provider, "baseUrl": saved.BaseURL,
			"modelName": saved.ModelName, "visionModelName": saved.VisionModelName,
			"autoRoute": saved.AutoRoute, "isDefault": saved.IsDefault, "apiKey": "[REDACTED]",
		}),
	})
	return s.repo.UserModelServiceByID(ctx, uid, id)
}

func (s *GovernanceService) DeleteUserModelService(ctx context.Context, uid, id int64) error {
	if uid <= 0 || id <= 0 {
		return ErrInvalidInput
	}
	if _, err := s.ensureUserModelServices(ctx, uid); err != nil {
		return err
	}
	item, err := s.repo.UserModelServiceByID(ctx, uid, id)
	if err != nil {
		return err
	}
	if item == nil {
		return ErrNotFound
	}
	deleted, err := s.repo.DeleteUserModelService(ctx, uid, id)
	if err != nil {
		return err
	}
	if !deleted {
		return ErrNotFound
	}
	if item.IsDefault {
		if err := s.repo.SetFirstUserModelServiceDefault(ctx, uid); err != nil {
			return err
		}
	}
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID: nil, ActorUserID: uid, Action: "user.model_service.delete",
		ResourceType: "user_model_service", ResourceID: strconv.FormatInt(id, 10), Result: "SUCCESS",
	})
	return nil
}

func (s *GovernanceService) modelRuntimeForService(ctx context.Context, uid int64, item model.UserModelService) (*runtimeclient.ProjectModelRuntime, error) {
	key, err := s.decryptUserModelServiceKey(ctx, uid, item)
	if err != nil {
		return nil, err
	}
	return &runtimeclient.ProjectModelRuntime{
		ServiceID:       item.ID,
		ServiceName:     item.Name,
		Provider:        item.Provider,
		BaseURL:         item.BaseURL,
		ModelName:       item.ModelName,
		VisionModelName: item.VisionModelName,
		APIKey:          key,
		AutoRoute:       item.AutoRoute,
		IsDefault:       item.IsDefault,
	}, nil
}

func (s *GovernanceService) ResolveUserModelRuntimePool(ctx context.Context, uid int64, selection model.ModelSelection) ([]runtimeclient.ProjectModelRuntime, error) {
	selection, err := normalizeModelSelection(selection)
	if err != nil {
		return nil, err
	}
	items, err := s.ensureUserModelServices(ctx, uid)
	if err != nil {
		return nil, err
	}
	enabled := make([]model.UserModelService, 0, len(items))
	for _, item := range items {
		if item.Enabled {
			enabled = append(enabled, item)
		}
	}
	if len(enabled) == 0 {
		return nil, ErrModelProviderNotConfigured
	}

	selected := enabled
	if selection.Mode == "manual" {
		selected = nil
		for _, item := range enabled {
			if selection.ServiceID != nil && item.ID == *selection.ServiceID {
				selected = []model.UserModelService{item}
				break
			}
		}
		if len(selected) == 0 {
			return nil, ErrNotFound
		}
	} else {
		selected = selected[:0]
		for _, item := range enabled {
			if item.AutoRoute {
				selected = append(selected, item)
			}
		}
		if len(selected) == 0 {
			// A user may intentionally remove every personal service from auto
			// routing while keeping them available for manual selection. This is an
			// explicit personal-policy state and must not silently fall back to a
			// shared Project credential.
			return nil, ErrModelAutoRouteNotConfigured
		}
	}

	out := make([]runtimeclient.ProjectModelRuntime, 0, len(selected))
	for _, item := range selected {
		runtime, err := s.modelRuntimeForService(ctx, uid, item)
		if err != nil {
			return nil, err
		}
		out = append(out, *runtime)
	}
	return out, nil
}

func (s *GovernanceService) ResolveUserModelRuntime(ctx context.Context, uid int64) (*runtimeclient.ProjectModelRuntime, error) {
	items, err := s.ensureUserModelServices(ctx, uid)
	if err != nil {
		return nil, err
	}
	var chosen *model.UserModelService
	for index := range items {
		item := &items[index]
		if !item.Enabled {
			continue
		}
		if item.IsDefault {
			chosen = item
			break
		}
		if chosen == nil {
			chosen = item
		}
	}
	if chosen == nil {
		return nil, ErrModelProviderNotConfigured
	}
	return s.modelRuntimeForService(ctx, uid, *chosen)
}

// ResolveRequestModelRuntime keeps the historical single-runtime contract for
// subsystems such as knowledge ingestion. The default enabled personal service
// wins; a shared Project provider remains the fallback when no personal service
// is available.
func (s *GovernanceService) ResolveRequestModelRuntime(ctx context.Context, uid int64, projectID *int64) (*runtimeclient.ProjectModelRuntime, error) {
	personal, err := s.ResolveUserModelRuntime(ctx, uid)
	if err == nil && personal != nil {
		return personal, nil
	}
	if err != nil && !errors.Is(err, ErrModelProviderNotConfigured) {
		return nil, err
	}

	if projectID != nil && *projectID > 0 {
		projectModel, projectErr := s.ResolveProjectModelRuntime(ctx, uid, *projectID)
		if projectErr == nil && projectModel != nil {
			return projectModel, nil
		}
		if projectErr != nil && !errors.Is(projectErr, ErrInvalidInput) {
			return nil, projectErr
		}
	}
	return nil, ErrModelProviderNotConfigured
}

// ResolveRequestModelRuntimePool is the task execution contract. Personal model
// services form the request-local pool. A project provider is used only when the
// user has no enabled personal service, preserving the existing BYOK boundary.
func (s *GovernanceService) ResolveRequestModelRuntimePool(
	ctx context.Context,
	uid int64,
	projectID *int64,
	selection model.ModelSelection,
) ([]runtimeclient.ProjectModelRuntime, *runtimeclient.ProjectModelRuntime, model.ModelSelection, error) {
	normalized, err := normalizeModelSelection(selection)
	if err != nil {
		return nil, nil, model.ModelSelection{}, err
	}
	pool, personalErr := s.ResolveUserModelRuntimePool(ctx, uid, normalized)
	if personalErr == nil && len(pool) > 0 {
		return pool, nil, normalized, nil
	}
	if normalized.Mode == "manual" {
		return nil, nil, normalized, personalErr
	}
	if personalErr != nil && !errors.Is(personalErr, ErrModelProviderNotConfigured) {
		return nil, nil, normalized, personalErr
	}

	if projectID != nil && *projectID > 0 {
		projectModel, projectErr := s.ResolveProjectModelRuntime(ctx, uid, *projectID)
		if projectErr == nil && projectModel != nil {
			return nil, projectModel, normalized, nil
		}
		if projectErr != nil && !errors.Is(projectErr, ErrInvalidInput) {
			return nil, nil, normalized, projectErr
		}
	}
	return nil, nil, normalized, ErrModelProviderNotConfigured
}

// -----------------------------------------------------------------------------
// Legacy single-provider API compatibility
// -----------------------------------------------------------------------------

func (s *GovernanceService) GetUserModelProvider(ctx context.Context, uid int64) (*model.UserModelProvider, error) {
	items, err := s.ensureUserModelServices(ctx, uid)
	if err != nil {
		return nil, err
	}
	for _, item := range items {
		if item.IsDefault || len(items) == 1 {
			return &model.UserModelProvider{
				UserID: item.UserID, Provider: item.Provider, BaseURL: item.BaseURL,
				ModelName: item.ModelName, VisionModelName: item.VisionModelName,
				MaskedHint: item.MaskedHint, Enabled: item.Enabled,
				CreatedAt: item.CreatedAt, UpdatedAt: item.UpdatedAt,
			}, nil
		}
	}
	if len(items) > 0 {
		item := items[0]
		return &model.UserModelProvider{
			UserID: item.UserID, Provider: item.Provider, BaseURL: item.BaseURL,
			ModelName: item.ModelName, VisionModelName: item.VisionModelName,
			MaskedHint: item.MaskedHint, Enabled: item.Enabled,
			CreatedAt: item.CreatedAt, UpdatedAt: item.UpdatedAt,
		}, nil
	}
	return nil, nil
}

func (s *GovernanceService) UpsertUserModelProvider(ctx context.Context, uid int64, input model.UserModelProviderInput) (*model.UserModelProvider, error) {
	items, err := s.ensureUserModelServices(ctx, uid)
	if err != nil {
		return nil, err
	}
	serviceInput := model.UserModelServiceInput{
		Name: userModelServiceName(input.Provider), Provider: input.Provider,
		BaseURL: input.BaseURL, ModelName: input.ModelName, VisionModelName: input.VisionModelName,
		APIKey: input.APIKey, Enabled: input.Enabled, AutoRoute: true, IsDefault: true,
	}
	if len(items) == 0 {
		if strings.TrimSpace(serviceInput.APIKey) == "" {
			return nil, ErrInvalidInput
		}
		if _, err = s.CreateUserModelService(ctx, uid, serviceInput); err != nil {
			return nil, err
		}
	} else {
		id := items[0].ID
		for _, item := range items {
			if item.IsDefault {
				id = item.ID
				break
			}
		}
		if _, err = s.UpdateUserModelService(ctx, uid, id, serviceInput); err != nil {
			return nil, err
		}
	}
	return s.GetUserModelProvider(ctx, uid)
}

func (s *GovernanceService) DeleteUserModelProvider(ctx context.Context, uid int64) error {
	if uid <= 0 {
		return ErrInvalidInput
	}
	count, err := s.repo.DeleteAllUserModelServices(ctx, uid)
	if err != nil {
		return err
	}
	legacyDeleted, legacyErr := s.repo.DeleteUserModelProvider(ctx, uid)
	if legacyErr != nil {
		return legacyErr
	}
	if count == 0 && !legacyDeleted {
		return ErrNotFound
	}
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID: nil, ActorUserID: uid, Action: "user.model_provider.delete",
		ResourceType: "user_model_provider", ResourceID: strconv.FormatInt(uid, 10), Result: "SUCCESS",
	})
	return nil
}

func (s *GovernanceService) CreateOrganization(ctx context.Context, uid int64, name string) (*model.Organization, error) {
	name = strings.TrimSpace(name)
	if uid <= 0 || name == "" || len(name) > 120 {
		return nil, ErrInvalidInput
	}
	return s.repo.CreateOrganization(ctx, uid, name)
}
func (s *GovernanceService) ListOrganizations(ctx context.Context, uid int64) ([]model.Organization, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}
	return s.repo.ListOrganizations(ctx, uid)
}
func (s *GovernanceService) AddOrganizationMember(ctx context.Context, uid, orgID int64, email, role string) (*model.OrganizationMember, error) {
	actorRole, err := s.repo.OrganizationRole(ctx, uid, orgID)
	if err != nil {
		return nil, err
	}
	if roleRank(actorRole) < roleRank("ADMIN") {
		return nil, ErrForbidden
	}
	role = strings.ToUpper(strings.TrimSpace(role))
	if !validAssignableRole(role) {
		return nil, ErrInvalidInput
	}
	item, err := s.repo.UpsertOrganizationMemberByEmail(ctx, orgID, strings.ToLower(strings.TrimSpace(email)), role)
	if item == nil && err == nil {
		return nil, ErrNotFound
	}
	return item, err
}
func (s *GovernanceService) BindProjectToOrganization(ctx context.Context, uid, orgID, projectID int64) error {
	// 当前用户至少必须是团队管理员。
	role, err := s.repo.OrganizationRole(ctx, uid, orgID)
	if err != nil {
		return err
	}
	if roleRank(role) < roleRank("ADMIN") {
		return ErrForbidden
	}

	// 当前用户必须是真正的项目所有者。
	projectRole, err := s.repo.ProjectRole(ctx, uid, projectID)
	if err != nil {
		return err
	}
	if projectRole != "OWNER" {
		return ErrForbidden
	}

	err = s.repo.BindProjectToOrganization(
		ctx,
		orgID,
		projectID,
		uid,
	)

	if errors.Is(err, repository.ErrNotOwned) {
		return ErrForbidden
	}

	if errors.Is(err, repository.ErrProjectAlreadyBound) {
		return ErrProjectAlreadyBound
	}

	return err
}
