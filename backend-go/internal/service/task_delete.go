package service

import (
	"context"
	"errors"
	"strings"
)

// taskDeleteRepository is a narrow optional capability.
//
// TaskService keeps using the existing repository.TaskRepository contract.
// The concrete MySQL repository additionally implements this capability.
//
// This lets us add Task deletion without forcing a broad repository
// interface rewrite across unrelated tests / fakes.
type taskDeleteRepository interface {
	DeleteTask(
		context.Context,
		int64,
		int64,
	) (bool, error)
}

func (s *TaskService) Delete(
	ctx context.Context,
	uid int64,
	taskID int64,
) error {
	if taskID <= 0 {
		return ErrInvalidInput
	}

	task, err := s.tasks.TaskByID(
		ctx,
		uid,
		taskID,
	)

	if err != nil {
		return err
	}

	if task == nil {
		return ErrNotFound
	}

	status := strings.ToUpper(
		strings.TrimSpace(
			task.Status,
		),
	)

	switch status {
	case
		"COMPLETED",
		"ERROR",
		"CANCELED":
		// terminal states can be removed from history

	case
		"RUNNING",
		"INPUT_REQUIRED",
		"AUTH_REQUIRED":
		// Deleting an active / resumable task can orphan Runtime state.
		// A future Cancel API should handle these states explicitly.
		return ErrConflict

	default:
		return ErrConflict
	}

	deleteRepo, ok := s.tasks.(taskDeleteRepository)

	if !ok {
		return errors.New(
			"task repository does not support delete",
		)
	}

	deleted, err :=
		deleteRepo.DeleteTask(
			ctx,
			uid,
			taskID,
		)

	if err != nil {
		return err
	}

	if !deleted {
		return ErrConflict
	}

	return nil
}
