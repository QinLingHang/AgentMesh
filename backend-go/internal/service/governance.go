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
	CreateOrganization(context.Context, int64, string) (*model.Organization, error)
	ListOrganizations(context.Context, int64) ([]model.Organization, error)
	OrganizationRole(context.Context, int64, int64) (string, error)
	UpsertOrganizationMemberByEmail(context.Context, int64, string, string) (*model.OrganizationMember, error)
	BindProjectToOrganization(context.Context, int64, int64, int64) error
	GetUserModelProvider(context.Context, int64) (*model.UserModelProvider, error)
	UserModelProviderCiphertext(context.Context, int64) ([]byte, []byte, error)
	UpsertUserModelProvider(context.Context, model.UserModelProvider, []byte, []byte) (*model.UserModelProvider, error)
	DeleteUserModelProvider(context.Context, int64) (bool, error)
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
	return &runtimeclient.ProjectModelRuntime{Provider: p.Provider, BaseURL: p.BaseURL, ModelName: p.ModelName, VisionModelName: p.ModelName, APIKey: key}, nil
}

func userModelAAD(uid int64) []byte {
	return []byte(fmt.Sprintf("agentmesh:user:%d:model-provider", uid))
}

func (s *GovernanceService) GetUserModelProvider(ctx context.Context, uid int64) (*model.UserModelProvider, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}
	return s.repo.GetUserModelProvider(ctx, uid)
}

func (s *GovernanceService) UpsertUserModelProvider(ctx context.Context, uid int64, input model.UserModelProviderInput) (*model.UserModelProvider, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	provider := strings.TrimSpace(input.Provider)
	baseURL := strings.TrimRight(strings.TrimSpace(input.BaseURL), "/")
	modelName := strings.TrimSpace(input.ModelName)
	visionModelName := strings.TrimSpace(input.VisionModelName)
	apiKey := strings.TrimSpace(input.APIKey)

	if provider == "" || len(provider) > 40 || modelName == "" || len(modelName) > 120 || len(visionModelName) > 120 || validateProviderURL(baseURL) != nil {
		return nil, ErrInvalidInput
	}
	if visionModelName == "" {
		visionModelName = modelName
	}

	existing, err := s.repo.GetUserModelProvider(ctx, uid)
	if err != nil {
		return nil, err
	}

	var ciphertext []byte
	var nonce []byte
	maskedHint := ""

	if apiKey != "" {
		if len(apiKey) > 16000 {
			return nil, ErrInvalidInput
		}
		nonce = make([]byte, s.aead.NonceSize())
		if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
			return nil, err
		}
		ciphertext = s.aead.Seal(nil, nonce, []byte(apiKey), userModelAAD(uid))
		maskedHint = maskHint(apiKey)
	} else {
		if existing == nil {
			return nil, ErrInvalidInput
		}
		ciphertext, nonce, err = s.repo.UserModelProviderCiphertext(ctx, uid)
		if err != nil {
			return nil, err
		}
		if len(ciphertext) == 0 || len(nonce) == 0 {
			return nil, ErrInvalidInput
		}
		maskedHint = existing.MaskedHint
	}

	item := model.UserModelProvider{
		UserID:          uid,
		Provider:        provider,
		BaseURL:         baseURL,
		ModelName:       modelName,
		VisionModelName: visionModelName,
		MaskedHint:      maskedHint,
		Enabled:         input.Enabled,
	}

	saved, err := s.repo.UpsertUserModelProvider(ctx, item, ciphertext, nonce)
	if err != nil {
		return nil, err
	}

	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID:    nil,
		ActorUserID:  uid,
		Action:       "user.model_provider.upsert",
		ResourceType: "user_model_provider",
		ResourceID:   strconv.FormatInt(uid, 10),
		Result:       "SUCCESS",
		Metadata: safeAuditMetadata(map[string]any{
			"provider":        provider,
			"baseUrl":         baseURL,
			"modelName":       modelName,
			"visionModelName": visionModelName,
			"apiKey":          "[REDACTED]",
		}),
	})

	return saved, nil
}

func (s *GovernanceService) DeleteUserModelProvider(ctx context.Context, uid int64) error {
	if uid <= 0 {
		return ErrInvalidInput
	}
	deleted, err := s.repo.DeleteUserModelProvider(ctx, uid)
	if err != nil {
		return err
	}
	if !deleted {
		return ErrNotFound
	}
	_ = s.repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID:    nil,
		ActorUserID:  uid,
		Action:       "user.model_provider.delete",
		ResourceType: "user_model_provider",
		ResourceID:   strconv.FormatInt(uid, 10),
		Result:       "SUCCESS",
	})
	return nil
}

func (s *GovernanceService) ResolveUserModelRuntime(ctx context.Context, uid int64) (*runtimeclient.ProjectModelRuntime, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}
	item, err := s.repo.GetUserModelProvider(ctx, uid)
	if err != nil {
		return nil, err
	}
	if item == nil || !item.Enabled {
		return nil, ErrModelProviderNotConfigured
	}
	ciphertext, nonce, err := s.repo.UserModelProviderCiphertext(ctx, uid)
	if err != nil {
		return nil, err
	}
	if len(ciphertext) == 0 || len(nonce) == 0 {
		return nil, ErrModelProviderNotConfigured
	}
	plain, err := s.aead.Open(nil, nonce, ciphertext, userModelAAD(uid))
	if err != nil {
		return nil, errors.New("user model secret decryption failed")
	}
	return &runtimeclient.ProjectModelRuntime{
		Provider:        item.Provider,
		BaseURL:         item.BaseURL,
		ModelName:       item.ModelName,
		VisionModelName: item.VisionModelName,
		APIKey:          string(plain),
	}, nil
}

// ResolveRequestModelRuntime makes user BYOK the default for authenticated
// requests. A shared Project provider is only a fallback when the user has not
// configured a personal provider. There is intentionally no platform-owner API
// key fallback here.
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
