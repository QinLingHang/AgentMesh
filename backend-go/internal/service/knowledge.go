package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"example.com/agentmesh-control-plane/internal/storage"

	"github.com/google/uuid"
)

var (
	ErrKnowledgeUnsupportedType = errors.New("unsupported knowledge file type")
	ErrKnowledgeTooLarge        = errors.New("knowledge file too large")
	ErrKnowledgeDefaultBase     = errors.New("default knowledge base cannot be deleted")
)

type knowledgeRepository interface {
	ProjectByID(
		context.Context,
		int64,
		int64,
	) (*model.Project, error)

	EnsureDefaultGlobalKnowledgeBase(
		context.Context,
		int64,
	) (*model.KnowledgeBase, error)

	EnsureDefaultProjectKnowledgeBase(
		context.Context,
		int64,
		int64,
		string,
	) (*model.KnowledgeBase, error)

	ListKnowledgeBases(
		context.Context,
		int64,
	) ([]model.KnowledgeBase, error)

	KnowledgeBaseByID(
		context.Context,
		int64,
		int64,
	) (*model.KnowledgeBase, error)

	CreateKnowledgeBase(
		context.Context,
		int64,
		string,
		string,
		string,
		model.KnowledgeBaseScope,
		*int64,
	) (*model.KnowledgeBase, error)

	UpdateKnowledgeBase(
		context.Context,
		int64,
		int64,
		string,
		string,
	) (*model.KnowledgeBase, error)

	DeleteKnowledgeBase(
		context.Context,
		int64,
		int64,
	) (bool, error)

	CreateKnowledgeFile(
		context.Context,
		model.KnowledgeFile,
	) (*model.KnowledgeFile, error)

	ListKnowledgeFilesByBase(
		context.Context,
		int64,
		int64,
	) ([]model.KnowledgeFile, error)

	ListKnowledgeFilesByProject(
		context.Context,
		int64,
		int64,
	) ([]model.KnowledgeFile, error)

	ListAllKnowledgeFiles(
		context.Context,
		int64,
	) ([]model.KnowledgeFile, error)

	KnowledgeFileByID(
		context.Context,
		int64,
		int64,
	) (*model.KnowledgeFile, error)

	DeleteKnowledgeFile(
		context.Context,
		int64,
		int64,
	) (bool, error)

	ListBoundGlobalKnowledgeBases(
		context.Context,
		int64,
		int64,
	) ([]model.KnowledgeBase, error)

	BindGlobalKnowledgeBase(
		context.Context,
		int64,
		int64,
		int64,
	) error

	UnbindGlobalKnowledgeBase(
		context.Context,
		int64,
		int64,
		int64,
	) error
}

type knowledgeIndexRepository interface {
	PrepareKnowledgeFileReindex(context.Context, int64, int64) (bool, error)
	MarkKnowledgeFileIndexing(context.Context, int64, int64) error
	CompleteKnowledgeFileIndex(context.Context, int64, int64, model.KnowledgeIndexResult) error
	FailKnowledgeFileIndex(context.Context, int64, int64, string) error
	ResolveRuntimeKnowledgeScope(context.Context, int64, *int64) (*model.RuntimeKnowledgeScope, error)
}

type knowledgeObjectReader interface {
	Open(context.Context, string) (io.ReadCloser, error)
}

type KnowledgeService struct {
	repo knowledgeRepository

	store storage.ObjectStore

	maxUploadBytes int64

	runtime *runtimeclient.Client

	governance *GovernanceService
}

func NewKnowledgeService(
	repo knowledgeRepository,
	store storage.ObjectStore,
	maxUploadBytes int64,
	runtimes ...*runtimeclient.Client,
) *KnowledgeService {
	var runtime *runtimeclient.Client
	if len(runtimes) > 0 {
		runtime = runtimes[0]
	}

	return &KnowledgeService{
		repo:           repo,
		store:          store,
		maxUploadBytes: maxUploadBytes,
		runtime:        runtime,
	}
}

func (s *KnowledgeService) SetGovernanceService(governance *GovernanceService) {
	s.governance = governance
}

func (s *KnowledgeService) MaxUploadBytes() int64 {
	return s.maxUploadBytes
}

func knowledgeFileNeedsVision(extension string) bool {
	switch strings.TrimPrefix(strings.ToLower(strings.TrimSpace(extension)), ".") {
	case "pdf", "png", "jpg", "jpeg", "webp":
		return true
	default:
		return false
	}
}

func normalizeKnowledgeExtension(
	name string,
) (string, error) {
	extension := strings.ToLower(
		filepath.Ext(
			strings.TrimSpace(name),
		),
	)

	switch extension {
	case ".pdf", ".docx", ".txt", ".md", ".markdown", ".png", ".jpg", ".jpeg", ".webp":
		return strings.TrimPrefix(extension, "."), nil
	default:
		return "", ErrKnowledgeUnsupportedType
	}
}

func validateKnowledgeBaseText(
	name string,
	description string,
) (string, string, error) {
	name = strings.TrimSpace(name)
	description = strings.TrimSpace(description)

	if name == "" ||
		utf8.RuneCountInString(name) > 80 ||
		utf8.RuneCountInString(description) > 240 {
		return "", "", ErrInvalidInput
	}

	return name, description, nil
}

func (s *KnowledgeService) ensureProject(
	ctx context.Context,
	uid int64,
	projectID int64,
) (*model.Project, error) {
	if projectID <= 0 {
		return nil, ErrInvalidInput
	}

	project, err := s.repo.ProjectByID(ctx, uid, projectID)
	if err != nil {
		return nil, err
	}
	if project == nil {
		return nil, ErrNotFound
	}

	return project, nil
}

func (s *KnowledgeService) ensureDefaultProjectBase(
	ctx context.Context,
	uid int64,
	projectID int64,
) (*model.KnowledgeBase, error) {
	project, err := s.ensureProject(ctx, uid, projectID)
	if err != nil {
		return nil, err
	}

	return s.repo.EnsureDefaultProjectKnowledgeBase(
		ctx,
		project.UserID,
		projectID,
		project.Name,
	)
}

func (s *KnowledgeService) ListBases(
	ctx context.Context,
	uid int64,
) ([]model.KnowledgeBase, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	if _, err := s.repo.EnsureDefaultGlobalKnowledgeBase(ctx, uid); err != nil {
		return nil, err
	}

	return s.repo.ListKnowledgeBases(ctx, uid)
}

func (s *KnowledgeService) CreateBase(
	ctx context.Context,
	uid int64,
	name string,
	description string,
	scope model.KnowledgeBaseScope,
	projectID *int64,
) (*model.KnowledgeBase, error) {
	name, description, err := validateKnowledgeBaseText(name, description)
	if err != nil {
		return nil, err
	}

	switch scope {
	case model.KnowledgeBaseScopeGlobal:
		projectID = nil

	case model.KnowledgeBaseScopeProject:
		if projectID == nil {
			return nil, ErrInvalidInput
		}
		if _, err = s.ensureProject(ctx, uid, *projectID); err != nil {
			return nil, err
		}

	default:
		return nil, ErrInvalidInput
	}

	identity := strings.ToLower(string(scope)) + ":" + uuid.NewString()

	return s.repo.CreateKnowledgeBase(
		ctx,
		uid,
		identity,
		name,
		description,
		scope,
		projectID,
	)
}

func (s *KnowledgeService) UpdateBase(
	ctx context.Context,
	uid int64,
	baseID int64,
	name string,
	description string,
) (*model.KnowledgeBase, error) {
	if baseID <= 0 {
		return nil, ErrInvalidInput
	}

	name, description, err := validateKnowledgeBaseText(name, description)
	if err != nil {
		return nil, err
	}

	base, err := s.repo.UpdateKnowledgeBase(
		ctx,
		uid,
		baseID,
		name,
		description,
	)
	if err != nil {
		return nil, err
	}
	if base == nil {
		return nil, ErrNotFound
	}

	return base, nil
}

func (s *KnowledgeService) DeleteBase(
	ctx context.Context,
	uid int64,
	baseID int64,
) error {
	if baseID <= 0 {
		return ErrInvalidInput
	}

	base, err := s.repo.KnowledgeBaseByID(ctx, uid, baseID)
	if err != nil {
		return err
	}
	if base == nil {
		return ErrNotFound
	}
	if base.IsDefault {
		return ErrKnowledgeDefaultBase
	}

	files, err := s.repo.ListKnowledgeFilesByBase(ctx, uid, baseID)
	if err != nil {
		return err
	}

	for _, file := range files {
		if s.runtime != nil {
			if err = s.runtime.DeleteKnowledge(ctx, file); err != nil {
				return err
			}
		}
		if err = s.store.Delete(ctx, file.StorageKey); err != nil {
			return err
		}
	}

	deleted, err := s.repo.DeleteKnowledgeBase(ctx, uid, baseID)
	if err != nil {
		return err
	}
	if !deleted {
		return ErrConflict
	}

	return nil
}

func (s *KnowledgeService) ListFilesByBase(
	ctx context.Context,
	uid int64,
	baseID int64,
) ([]model.KnowledgeFile, error) {
	if baseID <= 0 {
		return nil, ErrInvalidInput
	}

	base, err := s.repo.KnowledgeBaseByID(ctx, uid, baseID)
	if err != nil {
		return nil, err
	}
	if base == nil {
		return nil, ErrNotFound
	}

	return s.repo.ListKnowledgeFilesByBase(ctx, uid, baseID)
}

func (s *KnowledgeService) ListProjectFiles(
	ctx context.Context,
	uid int64,
	projectID int64,
) ([]model.KnowledgeFile, error) {
	if _, err := s.ensureDefaultProjectBase(ctx, uid, projectID); err != nil {
		return nil, err
	}

	return s.repo.ListKnowledgeFilesByProject(ctx, uid, projectID)
}

func (s *KnowledgeService) ListAll(
	ctx context.Context,
	uid int64,
) ([]model.KnowledgeFile, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	if _, err := s.repo.EnsureDefaultGlobalKnowledgeBase(ctx, uid); err != nil {
		return nil, err
	}

	return s.repo.ListAllKnowledgeFiles(ctx, uid)
}

func (s *KnowledgeService) UploadToBase(
	ctx context.Context,
	uid int64,
	baseID int64,
	originalName string,
	mediaType string,
	source io.Reader,
) (*model.KnowledgeFile, error) {
	if baseID <= 0 || source == nil || strings.TrimSpace(originalName) == "" {
		return nil, ErrInvalidInput
	}

	base, err := s.repo.KnowledgeBaseByID(ctx, uid, baseID)
	if err != nil {
		return nil, err
	}
	if base == nil {
		return nil, ErrNotFound
	}
	if base.Scope == model.KnowledgeBaseScopeProject && base.ProjectID != nil && s.governance != nil {
		if _, roleErr := s.governance.RequireRole(ctx, uid, *base.ProjectID, "DEVELOPER"); roleErr != nil {
			return nil, roleErr
		}
	}

	extension, err := normalizeKnowledgeExtension(originalName)
	if err != nil {
		return nil, err
	}

	storageScope := "global"
	if base.Scope == model.KnowledgeBaseScopeProject && base.ProjectID != nil {
		storageScope = "p" + fmt.Sprint(*base.ProjectID)
	}

	storageOwner := uid
	if base.Scope == model.KnowledgeBaseScopeProject {
		storageOwner = base.UserID
	}
	key := fmt.Sprintf(
		"u%d/%s/kb%d/%s.%s",
		storageOwner,
		storageScope,
		base.ID,
		uuid.NewString(),
		extension,
	)

	info, err := s.store.Put(ctx, key, source, s.maxUploadBytes)
	if errors.Is(err, storage.ErrObjectTooLarge) {
		return nil, ErrKnowledgeTooLarge
	}
	if err != nil {
		return nil, err
	}
	if info.SizeBytes <= 0 {
		_ = s.store.Delete(ctx, key)
		return nil, ErrInvalidInput
	}

	mediaType = strings.TrimSpace(mediaType)
	if mediaType == "" {
		mediaType = "application/octet-stream"
	}

	file, err := s.repo.CreateKnowledgeFile(
		ctx,
		model.KnowledgeFile{
			KnowledgeBaseID: base.ID,
			Scope:           base.Scope,
			ProjectID:       base.ProjectID,
			UserID:          storageOwner,
			OriginalName: strings.TrimSpace(
				filepath.Base(originalName),
			),
			MediaType:      mediaType,
			Extension:      extension,
			SizeBytes:      info.SizeBytes,
			ChecksumSHA256: info.SHA256,
			StorageKey:     key,
			Status:         "UPLOADED",
			ChunkCount:     0,
		},
	)
	if err != nil {
		_ = s.store.Delete(ctx, key)
		return nil, err
	}

	s.enqueueIndex(*file)

	return file, nil
}

// UploadProject is the compatibility path used by Project Home.
// It resolves the Project's default PROJECT knowledge base, then uploads there.
func (s *KnowledgeService) UploadProject(
	ctx context.Context,
	uid int64,
	projectID int64,
	originalName string,
	mediaType string,
	source io.Reader,
) (*model.KnowledgeFile, error) {
	if s.governance != nil {
		if _, err := s.governance.RequireRole(ctx, uid, projectID, "DEVELOPER"); err != nil {
			return nil, err
		}
	}
	base, err := s.ensureDefaultProjectBase(ctx, uid, projectID)
	if err != nil {
		return nil, err
	}

	return s.UploadToBase(
		ctx,
		uid,
		base.ID,
		originalName,
		mediaType,
		source,
	)
}

func (s *KnowledgeService) DeleteFile(
	ctx context.Context,
	uid int64,
	fileID int64,
) error {
	if fileID <= 0 {
		return ErrInvalidInput
	}

	file, err := s.repo.KnowledgeFileByID(ctx, uid, fileID)
	if err != nil {
		return err
	}
	if file == nil {
		return ErrNotFound
	}
	if file.ProjectID != nil && s.governance != nil {
		if _, roleErr := s.governance.RequireRole(ctx, uid, *file.ProjectID, "DEVELOPER"); roleErr != nil {
			return roleErr
		}
	}

	if s.runtime != nil {
		if err = s.runtime.DeleteKnowledge(ctx, *file); err != nil {
			return err
		}
	}

	if err = s.store.Delete(ctx, file.StorageKey); err != nil {
		return err
	}

	deleted, err := s.repo.DeleteKnowledgeFile(ctx, uid, fileID)
	if err != nil {
		return err
	}
	if !deleted {
		return ErrNotFound
	}

	return nil
}

func (s *KnowledgeService) DeleteProjectFile(
	ctx context.Context,
	uid int64,
	projectID int64,
	fileID int64,
) error {
	if projectID <= 0 || fileID <= 0 {
		return ErrInvalidInput
	}

	file, err := s.repo.KnowledgeFileByID(ctx, uid, fileID)
	if err != nil {
		return err
	}
	if file == nil || file.ProjectID == nil || *file.ProjectID != projectID || file.Scope != model.KnowledgeBaseScopeProject {
		return ErrNotFound
	}

	return s.DeleteFile(ctx, uid, fileID)
}

func (s *KnowledgeService) ListGlobalBindings(
	ctx context.Context,
	uid int64,
	projectID int64,
) ([]model.KnowledgeBase, error) {
	if _, err := s.ensureProject(ctx, uid, projectID); err != nil {
		return nil, err
	}

	if _, err := s.repo.EnsureDefaultGlobalKnowledgeBase(ctx, uid); err != nil {
		return nil, err
	}

	return s.repo.ListBoundGlobalKnowledgeBases(ctx, uid, projectID)
}

func (s *KnowledgeService) BindGlobal(
	ctx context.Context,
	uid int64,
	projectID int64,
	baseID int64,
) error {
	if _, err := s.ensureProject(ctx, uid, projectID); err != nil {
		return err
	}

	base, err := s.repo.KnowledgeBaseByID(ctx, uid, baseID)
	if err != nil {
		return err
	}
	if base == nil || base.Scope != model.KnowledgeBaseScopeGlobal {
		return ErrNotFound
	}

	err = s.repo.BindGlobalKnowledgeBase(ctx, uid, projectID, baseID)
	if errors.Is(err, repository.ErrNotOwned) {
		return ErrNotFound
	}
	return err
}

func (s *KnowledgeService) UnbindGlobal(
	ctx context.Context,
	uid int64,
	projectID int64,
	baseID int64,
) error {
	if _, err := s.ensureProject(ctx, uid, projectID); err != nil {
		return err
	}

	return s.repo.UnbindGlobalKnowledgeBase(ctx, uid, projectID, baseID)
}

// CleanupProject removes only PROJECT-scoped physical knowledge files.
// GLOBAL Knowledge Bases survive Project deletion; their binding rows cascade away.
func (s *KnowledgeService) CleanupProject(
	ctx context.Context,
	uid int64,
	projectID int64,
) error {
	files, err := s.repo.ListKnowledgeFilesByProject(ctx, uid, projectID)
	if err != nil {
		return err
	}

	for _, file := range files {
		if s.runtime != nil {
			if err = s.runtime.DeleteKnowledge(ctx, file); err != nil {
				return err
			}
		}
		if err = s.store.Delete(ctx, file.StorageKey); err != nil {
			return err
		}
	}

	return nil
}

// =========================================================
// Knowledge Ingestion / Runtime Scope
// =========================================================

func (s *KnowledgeService) enqueueIndex(file model.KnowledgeFile) {
	if s.runtime == nil {
		return
	}

	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 12*time.Minute)
		defer cancel()
		_ = s.indexFile(ctx, file.UserID, file.ID)
	}()
}

func (s *KnowledgeService) indexFile(
	ctx context.Context,
	uid int64,
	fileID int64,
) error {
	indexRepo, ok := s.repo.(knowledgeIndexRepository)
	if !ok {
		return errors.New("knowledge repository does not support indexing lifecycle")
	}

	readerStore, ok := s.store.(knowledgeObjectReader)
	if !ok {
		return errors.New("knowledge object store does not support reading")
	}

	file, err := s.repo.KnowledgeFileByID(ctx, uid, fileID)
	if err != nil {
		return err
	}
	if file == nil {
		return ErrNotFound
	}

	if err = indexRepo.MarkKnowledgeFileIndexing(ctx, uid, fileID); err != nil {
		return err
	}

	fail := func(cause error) error {
		message := "knowledge indexing failed"
		if cause != nil {
			message = cause.Error()
		}
		_ = indexRepo.FailKnowledgeFileIndex(context.Background(), uid, fileID, message)
		return cause
	}

	if s.runtime == nil {
		return fail(errors.New("knowledge runtime is not configured"))
	}

	source, err := readerStore.Open(ctx, file.StorageKey)
	if err != nil {
		return fail(err)
	}
	defer source.Close()

	var projectModel *runtimeclient.ProjectModelRuntime
	if s.governance != nil && knowledgeFileNeedsVision(file.Extension) {
		// BYOK plaintext is only needed by the internal Vision path. Avoid carrying
		// a user's model secret through text-only ingestion where it has no role.
		resolved, resolveErr := s.governance.ResolveRequestModelRuntime(ctx, uid, file.ProjectID)
		if resolveErr == nil {
			projectModel = resolved
		} else if !errors.Is(resolveErr, ErrModelProviderNotConfigured) {
			return fail(resolveErr)
		}
	}

	result, err := s.runtime.IndexKnowledge(ctx, *file, source, projectModel)
	if err != nil {
		return fail(err)
	}
	if result == nil || result.ChunkCount <= 0 {
		return fail(errors.New("knowledge runtime returned zero chunks"))
	}

	persistedResult := model.KnowledgeIndexResult{
		ChunkCount:          result.ChunkCount,
		TextChunkCount:      result.TextChunkCount,
		VisualEvidenceCount: result.VisualEvidenceCount,
		PageCount:           result.PageCount,
		VisualStatus:        result.VisualStatus,
		VisualError:         result.VisualError,
	}
	if err = indexRepo.CompleteKnowledgeFileIndex(ctx, uid, fileID, persistedResult); err != nil {
		return err
	}

	return nil
}

func (s *KnowledgeService) ReindexFile(
	ctx context.Context,
	uid int64,
	fileID int64,
) (*model.KnowledgeFile, error) {
	if fileID <= 0 {
		return nil, ErrInvalidInput
	}

	file, err := s.repo.KnowledgeFileByID(ctx, uid, fileID)
	if err != nil {
		return nil, err
	}
	if file == nil {
		return nil, ErrNotFound
	}

	indexRepo, ok := s.repo.(knowledgeIndexRepository)
	if !ok {
		return nil, errors.New("knowledge repository does not support reindex")
	}

	updated, err := indexRepo.PrepareKnowledgeFileReindex(ctx, uid, fileID)
	if err != nil {
		return nil, err
	}
	if !updated {
		return nil, ErrNotFound
	}

	if s.runtime != nil {
		if err = s.runtime.DeleteKnowledge(ctx, *file); err != nil {
			_ = indexRepo.FailKnowledgeFileIndex(context.Background(), uid, fileID, err.Error())
			return nil, err
		}
	}

	file, err = s.repo.KnowledgeFileByID(ctx, uid, fileID)
	if err != nil {
		return nil, err
	}
	if file == nil {
		return nil, ErrNotFound
	}

	s.enqueueIndex(*file)
	return file, nil
}

func (s *KnowledgeService) RuntimeScope(
	ctx context.Context,
	uid int64,
	conversationID *int64,
) (*model.RuntimeKnowledgeScope, error) {
	if uid <= 0 {
		return nil, ErrInvalidInput
	}

	if _, err := s.repo.EnsureDefaultGlobalKnowledgeBase(ctx, uid); err != nil {
		return nil, err
	}

	indexRepo, ok := s.repo.(knowledgeIndexRepository)
	if !ok {
		return nil, errors.New("knowledge repository does not support runtime scope")
	}

	scope, err := indexRepo.ResolveRuntimeKnowledgeScope(ctx, uid, conversationID)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	return scope, err
}

// LiveAuthorizedKnowledgeBaseIDs re-checks current ownership and conversation
// binding at the point of retrieval. It does not grant new access: callers
// MUST intersect this result with the frozen effective RAG policy snapshot.
// This method does not create a default global knowledge base as a side effect.
func (s *KnowledgeService) LiveAuthorizedKnowledgeBaseIDs(
	ctx context.Context, uid int64, conversationID *int64, requested []int64,
) ([]int64, error) {
	if uid <= 0 || len(requested) > 256 {
		return nil, ErrInvalidInput
	}
	if len(requested) == 0 {
		return []int64{}, nil
	}
	indexRepo, ok := s.repo.(knowledgeIndexRepository)
	if !ok {
		return nil, errors.New("knowledge repository does not support runtime scope")
	}
	scope, err := indexRepo.ResolveRuntimeKnowledgeScope(ctx, uid, conversationID)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	bases, err := s.repo.ListKnowledgeBases(ctx, uid)
	if err != nil {
		return nil, err
	}
	return filterLiveKnowledgeIDs(scope, bases, uid, requested), nil
}

// filterLiveKnowledgeIDs is intentionally independent of the old scope ID
// list: it historically contains only project-bound globals whereas V1.1
// allows explicitly opted-in, user-owned global bases. The snapshot is still
// the upper bound and the project conversation is validated by the repository.
func filterLiveKnowledgeIDs(
	scope *model.RuntimeKnowledgeScope, bases []model.KnowledgeBase,
	uid int64, requested []int64,
) []int64 {
	if scope == nil || uid <= 0 || scope.UserID != uid {
		return []int64{}
	}
	available := make(map[int64]bool, len(bases))
	for _, base := range bases {
		switch base.Scope {
		case model.KnowledgeBaseScopeGlobal:
			if base.UserID == uid {
				available[base.ID] = true
			}
		case model.KnowledgeBaseScopeProject:
			if scope.ProjectID != nil && base.ProjectID != nil && *scope.ProjectID == *base.ProjectID {
				available[base.ID] = true
			}
		}
	}
	seen := make(map[int64]bool, len(requested))
	result := make([]int64, 0, len(requested))
	for _, id := range requested {
		if id > 0 && available[id] && !seen[id] {
			seen[id] = true
			result = append(result, id)
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i] < result[j] })
	return result
}
