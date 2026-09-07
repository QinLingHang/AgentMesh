package service

import (
	"context"
	"strings"
	"unicode/utf8"

	"example.com/agentmesh-control-plane/internal/model"
)

type conversationTitleRepository interface {
	UpdateConversationTitle(
		context.Context,
		int64,
		int64,
		string,
	) (*model.Conversation, error)
}

func (s *ConversationService) Rename(
	ctx context.Context,
	uid int64,
	conversationID int64,
	title string,
) (*model.Conversation, error) {
	title = strings.TrimSpace(
		title,
	)

	if conversationID <= 0 ||
		title == "" ||
		utf8.RuneCountInString(
			title,
		) > 120 {
		return nil,
			ErrInvalidInput
	}

	repo, ok := s.repo.(conversationTitleRepository)

	if !ok {
		return nil,
			ErrConflict
	}

	conversation, err :=
		repo.UpdateConversationTitle(
			ctx,
			uid,
			conversationID,
			title,
		)

	if err != nil {
		return nil,
			err
	}

	if conversation == nil {
		return nil,
			ErrNotFound
	}

	return conversation,
		nil
}
