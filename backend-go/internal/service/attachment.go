package service

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"example.com/agentmesh-control-plane/internal/storage"

	"github.com/google/uuid"
)

var (
	ErrAttachmentUnsupportedType = errors.New("unsupported conversation attachment type")
	ErrAttachmentTooLarge        = errors.New("conversation attachment too large")
	ErrAttachmentLimit           = errors.New("conversation attachment limit exceeded")
)

const (
	attachmentHardMaxBytes int64 = 10 << 20
	attachmentMaxRunBytes  int64 = 20 << 20
	attachmentMaxRunCount        = 6
)

type attachmentObjectStore interface {
	Put(context.Context, string, io.Reader, int64) (storage.ObjectInfo, error)
	Open(context.Context, string) (io.ReadCloser, error)
	Delete(context.Context, string) error
}

type AttachmentService struct {
	repo           repository.AttachmentRepository
	objects        attachmentObjectStore
	maxUploadBytes int64
}

func NewAttachmentService(repo repository.AttachmentRepository, objects attachmentObjectStore, configuredMaxBytes int64) *AttachmentService {
	maxBytes := configuredMaxBytes
	if maxBytes <= 0 || maxBytes > attachmentHardMaxBytes {
		maxBytes = attachmentHardMaxBytes
	}
	return &AttachmentService{repo: repo, objects: objects, maxUploadBytes: maxBytes}
}

func (s *AttachmentService) MaxUploadBytes() int64 { return s.maxUploadBytes }

func normalizeAttachmentType(filename, mediaType string) (string, string, error) {
	name := strings.TrimSpace(filename)
	ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(name), "."))
	if ext == "jpeg" {
		ext = "jpg"
	}
	allowed := map[string]string{
		"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
		"pdf":  "application/pdf",
		"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"txt":  "text/plain", "md": "text/markdown", "markdown": "text/markdown",
		"csv": "text/csv", "json": "application/json",
	}
	canonical, ok := allowed[ext]
	if !ok {
		return "", "", ErrAttachmentUnsupportedType
	}
	mediaType = strings.TrimSpace(strings.Split(mediaType, ";")[0])
	if mediaType == "" || mediaType == "application/octet-stream" {
		mediaType = canonical
	}
	// Extension is the primary allow-list. Normalize image media types to avoid
	// claiming a text file as a multimodal image from a spoofed browser header.
	if strings.HasPrefix(canonical, "image/") && mediaType != canonical {
		return "", "", ErrAttachmentUnsupportedType
	}
	return ext, canonical, nil
}

func (s *AttachmentService) Upload(ctx context.Context, uid, conversationID int64, filename, mediaType string, source io.Reader) (*model.ConversationAttachment, error) {
	if uid <= 0 || conversationID <= 0 || strings.TrimSpace(filename) == "" || source == nil {
		return nil, ErrInvalidInput
	}
	ext, canonical, err := normalizeAttachmentType(filename, mediaType)
	if err != nil {
		return nil, err
	}
	key := fmt.Sprintf("attachments/%d/%d/%s.%s", uid, conversationID, uuid.NewString(), ext)
	info, err := s.objects.Put(ctx, key, source, s.maxUploadBytes)
	if errors.Is(err, storage.ErrObjectTooLarge) {
		return nil, ErrAttachmentTooLarge
	}
	if err != nil {
		return nil, err
	}
	item, err := s.repo.CreateConversationAttachment(ctx, model.ConversationAttachment{
		UserID: uid, ConversationID: conversationID, OriginalName: filepath.Base(filename),
		MediaType: canonical, Extension: ext, SizeBytes: info.SizeBytes,
		ChecksumSHA256: info.SHA256, StorageKey: key,
	})
	if errors.Is(err, repository.ErrNotOwned) {
		_ = s.objects.Delete(ctx, key)
		return nil, ErrNotFound
	}
	if err != nil {
		_ = s.objects.Delete(ctx, key)
		return nil, err
	}
	return item, nil
}

func (s *AttachmentService) List(ctx context.Context, uid, conversationID int64) ([]model.ConversationAttachment, error) {
	items, err := s.repo.ListConversationAttachments(ctx, uid, conversationID)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	return items, err
}

func (s *AttachmentService) Delete(ctx context.Context, uid, conversationID, attachmentID int64) error {
	item, err := s.repo.ConversationAttachmentByID(ctx, uid, conversationID, attachmentID)
	if err != nil {
		return err
	}
	if item == nil {
		return ErrNotFound
	}
	deleted, err := s.repo.DeleteConversationAttachment(ctx, uid, conversationID, attachmentID)
	if err != nil {
		return err
	}
	if !deleted {
		return ErrNotFound
	}
	_ = s.objects.Delete(ctx, item.StorageKey)
	return nil
}

func (s *AttachmentService) DeleteAllForConversation(ctx context.Context, uid, conversationID int64) error {
	items, err := s.repo.ListConversationAttachments(ctx, uid, conversationID)
	if errors.Is(err, repository.ErrNotOwned) {
		return ErrNotFound
	}
	if err != nil {
		return err
	}
	for _, item := range items {
		if err := s.objects.Delete(ctx, item.StorageKey); err != nil {
			return err
		}
	}
	return nil
}

func attachmentMetadata(items []model.ConversationAttachment) []map[string]any {
	result := make([]map[string]any, 0, len(items))
	for _, item := range items {
		result = append(result, map[string]any{
			"id": item.ID, "name": item.OriginalName, "mediaType": item.MediaType,
			"extension": item.Extension, "sizeBytes": item.SizeBytes,
		})
	}
	return result
}

func (s *AttachmentService) ResolveForRuntime(ctx context.Context, uid, conversationID int64, ids []int64) ([]runtimeclient.RuntimeAttachment, []map[string]any, error) {
	if len(ids) == 0 {
		return nil, nil, nil
	}
	if len(ids) > attachmentMaxRunCount {
		return nil, nil, ErrAttachmentLimit
	}
	seen := map[int64]struct{}{}
	items := make([]model.ConversationAttachment, 0, len(ids))
	var total int64
	for _, id := range ids {
		if id <= 0 {
			return nil, nil, ErrInvalidInput
		}
		if _, exists := seen[id]; exists {
			continue
		}
		seen[id] = struct{}{}
		item, err := s.repo.ConversationAttachmentByID(ctx, uid, conversationID, id)
		if err != nil {
			return nil, nil, err
		}
		if item == nil {
			return nil, nil, ErrNotFound
		}
		total += item.SizeBytes
		if total > attachmentMaxRunBytes {
			return nil, nil, ErrAttachmentLimit
		}
		items = append(items, *item)
	}
	transport := make([]runtimeclient.RuntimeAttachment, 0, len(items))
	for _, item := range items {
		reader, err := s.objects.Open(ctx, item.StorageKey)
		if err != nil {
			return nil, nil, err
		}
		data, readErr := io.ReadAll(io.LimitReader(reader, item.SizeBytes+1))
		_ = reader.Close()
		if readErr != nil {
			return nil, nil, readErr
		}
		if int64(len(data)) != item.SizeBytes {
			return nil, nil, errors.New("attachment object size mismatch")
		}
		transport = append(transport, runtimeclient.RuntimeAttachment{
			ID: item.ID, Name: item.OriginalName, MediaType: item.MediaType,
			Extension: item.Extension, SizeBytes: item.SizeBytes,
			ContentBase64: base64.StdEncoding.EncodeToString(data),
		})
	}
	return transport, attachmentMetadata(items), nil
}
