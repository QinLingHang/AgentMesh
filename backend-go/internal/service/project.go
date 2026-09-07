package service

import (
	"context"
	"strings"
	"unicode/utf8"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

type projectRepository interface {
	CreateProject(
		context.Context,
		int64,
		string,
		string,
	) (*model.Project, error)

	ListProjects(
		context.Context,
		int64,
	) ([]model.Project, error)

	ProjectByID(
		context.Context,
		int64,
		int64,
	) (*model.Project, error)

	UpdateProject(
		context.Context,
		int64,
		int64,
		string,
		string,
	) (*model.Project, error)

	DeleteProject(
		context.Context,
		int64,
		int64,
	) (bool, error)

	AssignConversationToProject(
		context.Context,
		int64,
		int64,
		int64,
	) error

	RemoveConversationFromProject(
		context.Context,
		int64,
		int64,
	) error
}

type projectResourceCleaner interface {
	CleanupProject(
		context.Context,
		int64,
		int64,
	) error
}

type ProjectService struct {
	repo projectRepository

	cleaners []projectResourceCleaner
}

func NewProjectService(
	repo projectRepository,
	cleaners ...projectResourceCleaner,
) *ProjectService {
	return &ProjectService{
		repo:     repo,
		cleaners: cleaners,
	}
}

func validateProjectText(
	name string,
	description string,
) (
	string,
	string,
	error,
) {
	name = strings.TrimSpace(
		name,
	)

	description =
		strings.TrimSpace(
			description,
		)

	if name == "" ||
		utf8.RuneCountInString(
			name,
		) > 80 ||
		utf8.RuneCountInString(
			description,
		) > 240 {
		return "",
			"",
			ErrInvalidInput
	}

	return name,
		description,
		nil
}

func (s *ProjectService) Create(
	ctx context.Context,
	uid int64,
	name string,
	description string,
) (*model.Project, error) {
	name,
		description,
		err :=
		validateProjectText(
			name,
			description,
		)

	if err != nil {
		return nil,
			err
	}

	return s.repo.CreateProject(
		ctx,
		uid,
		name,
		description,
	)
}

func (s *ProjectService) List(
	ctx context.Context,
	uid int64,
) ([]model.Project, error) {
	return s.repo.ListProjects(
		ctx,
		uid,
	)
}

func (s *ProjectService) Update(
	ctx context.Context,
	uid int64,
	projectID int64,
	name string,
	description string,
) (*model.Project, error) {
	name,
		description,
		err :=
		validateProjectText(
			name,
			description,
		)

	if err != nil ||
		projectID <= 0 {
		return nil,
			ErrInvalidInput
	}

	project, err :=
		s.repo.UpdateProject(
			ctx,
			uid,
			projectID,
			name,
			description,
		)

	if err != nil {
		return nil,
			err
	}

	if project == nil {
		return nil,
			ErrNotFound
	}

	return project,
		nil
}

func (s *ProjectService) Delete(
	ctx context.Context,
	uid int64,
	projectID int64,
) error {
	if projectID <= 0 {
		return ErrInvalidInput
	}

	for _, cleaner := range s.cleaners {
		if err := cleaner.CleanupProject(
			ctx,
			uid,
			projectID,
		); err != nil {
			return err
		}
	}

	deleted, err :=
		s.repo.DeleteProject(
			ctx,
			uid,
			projectID,
		)

	if err != nil {
		return err
	}

	if !deleted {
		return ErrNotFound
	}

	return nil
}

func (s *ProjectService) AssignConversation(
	ctx context.Context,
	uid int64,
	projectID int64,
	conversationID int64,
) error {
	if projectID <= 0 ||
		conversationID <= 0 {
		return ErrInvalidInput
	}

	err := s.repo.AssignConversationToProject(
		ctx,
		uid,
		projectID,
		conversationID,
	)

	if err == repository.ErrNotOwned {
		return ErrNotFound
	}

	return err
}

func (s *ProjectService) RemoveConversation(
	ctx context.Context,
	uid int64,
	conversationID int64,
) error {
	if conversationID <= 0 {
		return ErrInvalidInput
	}

	return s.repo.RemoveConversationFromProject(
		ctx,
		uid,
		conversationID,
	)
}
