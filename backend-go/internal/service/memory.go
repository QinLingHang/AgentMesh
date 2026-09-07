package service

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"unicode/utf8"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

const (
	defaultMemoryLimit = 100
	maxMemoryLimit     = 200
)

var memoryKeyPattern = regexp.MustCompile(
	`^[a-z0-9][a-z0-9._-]{0,127}$`,
)

var memoryCategories = map[string]struct{}{
	"preference": {},
	"profile":    {},
	"goal":       {},
	"workflow":   {},
	"fact":       {},
	"other":      {},
}

var memorySourceTypes = map[string]struct{}{
	"explicit_user": {},
	"inferred_user": {},
	"manual":        {},
}

var memoryStatuses = map[string]struct{}{
	"active": {},
}

type memoryRepository interface {
	CreateMemory(
		context.Context,
		int64,
		model.UserMemory,
	) (*model.UserMemory, error)

	MemoryByID(
		context.Context,
		int64,
		int64,
	) (*model.UserMemory, error)

	MemoryByKey(
		context.Context,
		int64,
		string,
	) (*model.UserMemory, error)

	ListMemories(
		context.Context,
		int64,
		model.MemoryFilter,
	) ([]model.UserMemory, error)

	ListActiveMemories(
		context.Context,
		int64,
		int,
	) ([]model.UserMemory, error)

	UpdateMemory(
		context.Context,
		int64,
		int64,
		model.UserMemory,
	) (*model.UserMemory, error)

	DeleteMemory(
		context.Context,
		int64,
		int64,
	) (bool, error)

	TouchMemoryAccess(
		context.Context,
		int64,
		int64,
	) error
}

type MemoryService struct {
	repo memoryRepository
}

func NewMemoryService(
	repo memoryRepository,
) *MemoryService {
	return &MemoryService{
		repo: repo,
	}
}

type CreateMemoryInput struct {
	Category string

	MemoryKey string

	Content string

	SourceType string

	Confidence *float64

	Status string
}

type UpdateMemoryInput struct {
	Category *string

	MemoryKey *string

	Content *string

	SourceType *string

	Confidence *float64

	Status *string
}

type MemoryListInput struct {
	Category string

	Status string

	Keyword string

	Limit int
}

// MemoryUpsertResult is returned by the internal P3.2 automatic-memory
// contract. The action is intentionally explicit so Runtime Trace can show
// whether a durable memory was created, updated, left unchanged, or preserved
// because an inferred candidate had lower authority than an existing memory.
type MemoryUpsertResult struct {
	Action string `json:"action"`

	Memory *model.UserMemory `json:"memory"`
}

func normalizeMemoryCategory(
	value string,
) (string, error) {
	value = strings.ToLower(
		strings.TrimSpace(
			value,
		),
	)

	if _, ok := memoryCategories[value]; !ok {
		return "", ErrInvalidInput
	}

	return value, nil
}

func normalizeMemoryKey(
	value string,
) (string, error) {
	value = strings.ToLower(
		strings.TrimSpace(
			value,
		),
	)

	if !memoryKeyPattern.MatchString(
		value,
	) {
		return "", ErrInvalidInput
	}

	return value, nil
}

func normalizeMemoryContent(
	value string,
) (string, error) {
	value = strings.TrimSpace(
		value,
	)

	if value == "" ||
		utf8.RuneCountInString(
			value,
		) > 8000 {
		return "", ErrInvalidInput
	}

	return value, nil
}

func normalizeMemorySourceType(
	value string,
) (string, error) {
	value = strings.ToLower(
		strings.TrimSpace(
			value,
		),
	)

	if value == "" {
		value = "explicit_user"
	}

	if _, ok := memorySourceTypes[value]; !ok {
		return "", ErrInvalidInput
	}

	return value, nil
}

func normalizeMemoryStatus(
	value string,
) (string, error) {
	value = strings.ToLower(
		strings.TrimSpace(
			value,
		),
	)

	if value == "" {
		value = "active"
	}

	if _, ok := memoryStatuses[value]; !ok {
		return "", ErrInvalidInput
	}

	return value, nil
}

func normalizeMemoryConfidence(
	value *float64,
) (float64, error) {
	if value == nil {
		return 1, nil
	}

	if *value < 0 ||
		*value > 1 {
		return 0, ErrInvalidInput
	}

	return *value, nil
}

func normalizeMemory(
	memory model.UserMemory,
) (model.UserMemory, error) {
	var err error

	memory.Category, err = normalizeMemoryCategory(
		memory.Category,
	)
	if err != nil {
		return model.UserMemory{}, err
	}

	memory.MemoryKey, err = normalizeMemoryKey(
		memory.MemoryKey,
	)
	if err != nil {
		return model.UserMemory{}, err
	}

	memory.Content, err = normalizeMemoryContent(
		memory.Content,
	)
	if err != nil {
		return model.UserMemory{}, err
	}

	memory.SourceType, err = normalizeMemorySourceType(
		memory.SourceType,
	)
	if err != nil {
		return model.UserMemory{}, err
	}

	memory.Status, err = normalizeMemoryStatus(
		memory.Status,
	)
	if err != nil {
		return model.UserMemory{}, err
	}

	if memory.Confidence < 0 ||
		memory.Confidence > 1 {
		return model.UserMemory{}, ErrInvalidInput
	}

	return memory, nil
}

func mapMemoryRepositoryError(
	err error,
) error {
	if errors.Is(
		err,
		repository.ErrMemoryKeyExists,
	) {
		return ErrAlreadyExists
	}

	return err
}

func (s *MemoryService) Create(
	ctx context.Context,
	uid int64,
	input CreateMemoryInput,
) (*model.UserMemory, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	confidence, err := normalizeMemoryConfidence(
		input.Confidence,
	)
	if err != nil {
		return nil, err
	}

	memory, err := normalizeMemory(
		model.UserMemory{
			UserID:     uid,
			Category:   input.Category,
			MemoryKey:  input.MemoryKey,
			Content:    input.Content,
			SourceType: input.SourceType,
			Confidence: confidence,
			Status:     input.Status,
		},
	)
	if err != nil {
		return nil, err
	}

	created, err := s.repo.CreateMemory(
		ctx,
		uid,
		memory,
	)

	return created, mapMemoryRepositoryError(
		err,
	)
}

func (s *MemoryService) Get(
	ctx context.Context,
	uid int64,
	id int64,
) (*model.UserMemory, error) {
	if uid <= 0 ||
		id <= 0 {
		return nil, ErrInvalidInput
	}

	memory, err := s.repo.MemoryByID(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return nil, err
	}

	if memory == nil {
		return nil, ErrNotFound
	}

	if err := s.repo.TouchMemoryAccess(
		ctx,
		uid,
		id,
	); err != nil {
		return nil, err
	}

	return s.repo.MemoryByID(
		ctx,
		uid,
		id,
	)
}

func (s *MemoryService) ByKey(
	ctx context.Context,
	uid int64,
	memoryKey string,
) (*model.UserMemory, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	memoryKey, err := normalizeMemoryKey(
		memoryKey,
	)
	if err != nil {
		return nil, err
	}

	memory, err := s.repo.MemoryByKey(
		ctx,
		uid,
		memoryKey,
	)

	if err != nil {
		return nil, err
	}

	if memory == nil {
		return nil, ErrNotFound
	}

	return memory, nil
}

// UpsertAutomatic is the Go-side persistence/ownership boundary for P3.2.
//
// It is deliberately key-based and user-global. There is no project_id in the
// contract. Automatic inferred memories are lower-authority than memories that
// were explicitly requested by the user or manually managed through the CRUD
// API, so an inferred write can never silently overwrite those sources.
func (s *MemoryService) UpsertAutomatic(
	ctx context.Context,
	uid int64,
	input CreateMemoryInput,
) (*MemoryUpsertResult, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	confidence, err := normalizeMemoryConfidence(
		input.Confidence,
	)
	if err != nil {
		return nil, err
	}

	incoming, err := normalizeMemory(
		model.UserMemory{
			UserID:     uid,
			Category:   input.Category,
			MemoryKey:  input.MemoryKey,
			Content:    input.Content,
			SourceType: input.SourceType,
			Confidence: confidence,
			Status:     input.Status,
		},
	)
	if err != nil {
		return nil, err
	}

	if incoming.SourceType != "explicit_user" &&
		incoming.SourceType != "inferred_user" {
		return nil, ErrInvalidInput
	}

	existing, err := s.repo.MemoryByKey(
		ctx,
		uid,
		incoming.MemoryKey,
	)
	if err != nil {
		return nil, err
	}

	if existing == nil {
		created, err := s.repo.CreateMemory(
			ctx,
			uid,
			incoming,
		)
		if err == nil {
			return &MemoryUpsertResult{
				Action: "created",
				Memory: created,
			}, nil
		}

		// A concurrent request may have inserted the same (user_id, memory_key)
		// between our read and create. Re-read and apply the same authority policy
		// rather than surfacing a duplicate-key race to Runtime.
		if !errors.Is(err, repository.ErrMemoryKeyExists) {
			return nil, mapMemoryRepositoryError(err)
		}

		existing, err = s.repo.MemoryByKey(
			ctx,
			uid,
			incoming.MemoryKey,
		)
		if err != nil {
			return nil, err
		}
		if existing == nil {
			return nil, ErrConflict
		}
	}

	if memorySourceAuthority(existing.SourceType) >
		memorySourceAuthority(incoming.SourceType) {
		return &MemoryUpsertResult{
			Action: "preserved",
			Memory: existing,
		}, nil
	}

	if sameDurableMemory(*existing, incoming) {
		return &MemoryUpsertResult{
			Action: "unchanged",
			Memory: existing,
		}, nil
	}

	incoming.ID = existing.ID
	incoming.CreatedAt = existing.CreatedAt
	incoming.LastAccessedAt = existing.LastAccessedAt

	updated, err := s.repo.UpdateMemory(
		ctx,
		uid,
		existing.ID,
		incoming,
	)
	if err != nil {
		return nil, mapMemoryRepositoryError(err)
	}
	if updated == nil {
		return nil, ErrNotFound
	}

	return &MemoryUpsertResult{
		Action: "updated",
		Memory: updated,
	}, nil
}

func memorySourceAuthority(sourceType string) int {
	switch strings.ToLower(strings.TrimSpace(sourceType)) {
	case "manual", "explicit_user":
		return 2
	case "inferred_user":
		return 1
	default:
		return 0
	}
}

func sameDurableMemory(
	left model.UserMemory,
	right model.UserMemory,
) bool {
	return left.Category == right.Category &&
		left.MemoryKey == right.MemoryKey &&
		left.Content == right.Content &&
		left.SourceType == right.SourceType &&
		left.Confidence == right.Confidence &&
		left.Status == right.Status
}

func normalizeMemoryListInput(
	input MemoryListInput,
) (model.MemoryFilter, error) {
	var filter model.MemoryFilter
	var err error

	if strings.TrimSpace(
		input.Category,
	) != "" {
		filter.Category, err = normalizeMemoryCategory(
			input.Category,
		)

		if err != nil {
			return model.MemoryFilter{}, err
		}
	}

	if strings.TrimSpace(
		input.Status,
	) != "" {
		filter.Status, err = normalizeMemoryStatus(
			input.Status,
		)

		if err != nil {
			return model.MemoryFilter{}, err
		}
	}

	filter.Keyword = strings.TrimSpace(
		input.Keyword,
	)

	if utf8.RuneCountInString(
		filter.Keyword,
	) > 128 {
		return model.MemoryFilter{}, ErrInvalidInput
	}

	filter.Limit = input.Limit
	if filter.Limit <= 0 {
		filter.Limit = defaultMemoryLimit
	}
	if filter.Limit > maxMemoryLimit {
		filter.Limit = maxMemoryLimit
	}

	return filter, nil
}

func (s *MemoryService) List(
	ctx context.Context,
	uid int64,
	input MemoryListInput,
) ([]model.UserMemory, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	filter, err := normalizeMemoryListInput(
		input,
	)
	if err != nil {
		return nil, err
	}

	return s.repo.ListMemories(
		ctx,
		uid,
		filter,
	)
}

func (s *MemoryService) ListActiveForUser(
	ctx context.Context,
	uid int64,
	limit int,
) ([]model.UserMemory, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	if limit <= 0 {
		limit = defaultMemoryLimit
	}
	if limit > maxMemoryLimit {
		limit = maxMemoryLimit
	}

	return s.repo.ListActiveMemories(
		ctx,
		uid,
		limit,
	)
}

func (s *MemoryService) Update(
	ctx context.Context,
	uid int64,
	id int64,
	input UpdateMemoryInput,
) (*model.UserMemory, error) {
	if uid <= 0 ||
		id <= 0 {
		return nil, ErrInvalidInput
	}

	if input.Category == nil &&
		input.MemoryKey == nil &&
		input.Content == nil &&
		input.SourceType == nil &&
		input.Confidence == nil &&
		input.Status == nil {
		return nil, ErrInvalidInput
	}

	memory, err := s.repo.MemoryByID(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return nil, err
	}

	if memory == nil {
		return nil, ErrNotFound
	}

	if input.Category != nil {
		memory.Category = *input.Category
	}
	if input.MemoryKey != nil {
		memory.MemoryKey = *input.MemoryKey
	}
	if input.Content != nil {
		memory.Content = *input.Content
	}
	if input.SourceType != nil {
		memory.SourceType = *input.SourceType
	}
	if input.Confidence != nil {
		memory.Confidence = *input.Confidence
	}
	if input.Status != nil {
		memory.Status = *input.Status
	}

	memory, err = func() (*model.UserMemory, error) {
		normalized, err := normalizeMemory(
			*memory,
		)

		if err != nil {
			return nil, err
		}

		return &normalized, nil
	}()

	if err != nil {
		return nil, err
	}

	updated, err := s.repo.UpdateMemory(
		ctx,
		uid,
		id,
		*memory,
	)

	if err != nil {
		return nil, mapMemoryRepositoryError(
			err,
		)
	}

	if updated == nil {
		return nil, ErrNotFound
	}

	return updated, nil
}

func (s *MemoryService) Delete(
	ctx context.Context,
	uid int64,
	id int64,
) error {
	if uid <= 0 ||
		id <= 0 {
		return ErrInvalidInput
	}

	deleted, err := s.repo.DeleteMemory(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return err
	}

	if !deleted {
		return ErrNotFound
	}

	return nil
}
