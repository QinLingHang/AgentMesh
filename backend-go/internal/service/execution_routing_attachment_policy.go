package service

import (
	"context"
	"strings"
)

// modelReadableAttachments is an optimization hint, never a permission.
// Only user-owned, existing, small, text-like request-local attachments may
// bypass discovery. The FastPath parser must still validate actual bytes and
// report parse/truncation errors instead of inventing document content.
func (s *TaskService) modelReadableAttachments(ctx context.Context, uid int64, in RunTaskInput) bool {
	if s.attachments == nil || in.ConversationID == nil || len(in.AttachmentIDs) == 0 || len(in.AttachmentIDs) > 2 ||
		(strings.Contains(in.Task, "两份") && len(in.AttachmentIDs) != 2) {
		return false
	}
	items, err := s.attachments.List(ctx, uid, *in.ConversationID)
	if err != nil {
		return false // The subsequent execution still enforces ownership.
	}
	owned := make(map[int64]struct {
		extension string
		size      int64
	}, len(items))
	for _, item := range items {
		owned[item.ID] = struct {
			extension string
			size      int64
		}{strings.ToLower(item.Extension), item.SizeBytes}
	}
	allowed := map[string]bool{"txt": true, "md": true, "markdown": true, "csv": true, "json": true}
	seen := make(map[int64]bool, len(in.AttachmentIDs))
	var total int64
	for _, id := range in.AttachmentIDs {
		item, ok := owned[id]
		if !ok || seen[id] || !allowed[item.extension] || item.size <= 0 {
			return false
		}
		seen[id] = true
		total += item.size
		if total > 32*1024 { // Below the FastPath document-context budget.
			return false
		}
	}
	return true
}
