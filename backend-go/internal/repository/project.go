package repository

import (
	"context"
	"database/sql"
	"errors"

	"example.com/agentmesh-control-plane/internal/model"
)

func scanProject(
	scanner scanner,
) (*model.Project, error) {
	var project model.Project

	err := scanner.Scan(
		&project.ID,
		&project.UserID,
		&project.Name,
		&project.Description,
		&project.CreatedAt,
		&project.UpdatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil,
			nil
	}

	if err != nil {
		return nil,
			err
	}

	project.ConversationIDs =
		[]int64{}

	return &project,
		nil
}

func (r *MySQL) CreateProject(
	ctx context.Context,
	uid int64,
	name string,
	description string,
) (*model.Project, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO projects(
			user_id,
			name,
			description
		)
		VALUES(
			?,
			?,
			?
		)
		`,
		uid,
		name,
		description,
	)

	if err != nil {
		return nil,
			err
	}

	id, err :=
		result.LastInsertId()

	if err != nil {
		return nil,
			err
	}

	return r.ProjectByID(
		ctx,
		uid,
		id,
	)
}

func (r *MySQL) ProjectByID(
	ctx context.Context,
	uid int64,
	projectID int64,
) (*model.Project, error) {
	project, err := scanProject(
		r.db.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				user_id,
				name,
				description,
				created_at,
				updated_at
			FROM projects p
			WHERE p.id = ?
			  AND (
				p.user_id = ?
				OR EXISTS (
					SELECT 1 FROM project_members pm
					WHERE pm.project_id = p.id AND pm.user_id = ?
				)
			  )
			LIMIT 1
			`,
			projectID,
			uid,
			uid,
		),
	)

	if err != nil ||
		project == nil {
		return project,
			err
	}

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT pc.conversation_id
		FROM project_conversations pc
		INNER JOIN conversations c
			ON c.id = pc.conversation_id
		WHERE pc.project_id = ?
		  AND c.user_id = ?
		ORDER BY
			c.updated_at DESC,
			c.id DESC
		`,
		project.ID,
		uid,
	)

	if err != nil {
		return nil,
			err
	}

	defer rows.Close()

	for rows.Next() {
		var conversationID int64

		if err = rows.Scan(
			&conversationID,
		); err != nil {
			return nil,
				err
		}

		project.ConversationIDs =
			append(
				project.ConversationIDs,
				conversationID,
			)
	}

	return project,
		rows.Err()
}

func (r *MySQL) ListProjects(
	ctx context.Context,
	uid int64,
) ([]model.Project, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			user_id,
			name,
			description,
			created_at,
			updated_at
		FROM projects p
		WHERE p.user_id = ?
		   OR EXISTS (
			SELECT 1 FROM project_members pm
			WHERE pm.project_id = p.id AND pm.user_id = ?
		   )
		ORDER BY
			updated_at DESC,
			id DESC
		`,
		uid,
		uid,
	)

	if err != nil {
		return nil,
			err
	}

	defer rows.Close()

	projects :=
		[]model.Project{}

	for rows.Next() {
		project, err :=
			scanProject(
				rows,
			)

		if err != nil {
			return nil,
				err
		}

		projects = append(
			projects,
			*project,
		)
	}

	if err = rows.Err(); err != nil {
		return nil,
			err
	}

	if err = rows.Close(); err != nil {
		return nil,
			err
	}

	mappingRows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			pc.project_id,
			pc.conversation_id
		FROM project_conversations pc
		INNER JOIN projects p
			ON p.id = pc.project_id
		INNER JOIN conversations c
			ON c.id = pc.conversation_id
		WHERE (p.user_id = ? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=?))
		  AND c.user_id = ?
		ORDER BY
			c.updated_at DESC,
			c.id DESC
		`,
		uid,
		uid,
		uid,
	)

	if err != nil {
		return nil,
			err
	}

	defer mappingRows.Close()

	byID :=
		make(
			map[int64]*model.Project,
			len(
				projects,
			),
		)

	for index := range projects {
		byID[projects[index].ID] = &projects[index]
	}

	for mappingRows.Next() {
		var projectID int64

		var conversationID int64

		if err = mappingRows.Scan(
			&projectID,
			&conversationID,
		); err != nil {
			return nil,
				err
		}

		if project := byID[projectID]; project != nil {
			project.ConversationIDs =
				append(
					project.ConversationIDs,
					conversationID,
				)
		}
	}

	return projects,
		mappingRows.Err()
}

func (r *MySQL) UpdateProject(
	ctx context.Context,
	uid int64,
	projectID int64,
	name string,
	description string,
) (*model.Project, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE projects
		SET
			name = ?,
			description = ?,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		name,
		description,
		projectID,
		uid,
	)

	if err != nil {
		return nil,
			err
	}

	affected, err :=
		result.RowsAffected()

	if err != nil {
		return nil,
			err
	}

	if affected == 0 {
		return nil,
			nil
	}

	return r.ProjectByID(
		ctx,
		uid,
		projectID,
	)
}

func (r *MySQL) DeleteProject(
	ctx context.Context,
	uid int64,
	projectID int64,
) (bool, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM projects
		WHERE id = ?
		  AND user_id = ?
		`,
		projectID,
		uid,
	)

	if err != nil {
		return false,
			err
	}

	affected, err :=
		result.RowsAffected()

	if err != nil {
		return false,
			err
	}

	return affected == 1,
		nil
}

func (r *MySQL) AssignConversationToProject(
	ctx context.Context,
	uid int64,
	projectID int64,
	conversationID int64,
) error {
	tx, err := r.db.BeginTx(
		ctx,
		nil,
	)

	if err != nil {
		return err
	}

	defer func() {
		_ = tx.Rollback()
	}()

	var projectOwner int64

	if err = tx.QueryRowContext(
		ctx,
		`
		SELECT user_id
		FROM projects
		WHERE id = ?
		LIMIT 1
		FOR UPDATE
		`,
		projectID,
	).Scan(
		&projectOwner,
	); err != nil {
		if errors.Is(
			err,
			sql.ErrNoRows,
		) {
			return ErrNotOwned
		}

		return err
	}

	var conversationOwner int64

	if err = tx.QueryRowContext(
		ctx,
		`
		SELECT user_id
		FROM conversations
		WHERE id = ?
		LIMIT 1
		FOR UPDATE
		`,
		conversationID,
	).Scan(
		&conversationOwner,
	); err != nil {
		if errors.Is(
			err,
			sql.ErrNoRows,
		) {
			return ErrNotOwned
		}

		return err
	}

	if conversationOwner != uid {
		return ErrNotOwned
	}
	if projectOwner != uid {
		var memberRole string
		if err = tx.QueryRowContext(ctx, `SELECT role FROM project_members WHERE project_id=? AND user_id=? LIMIT 1`, projectID, uid).Scan(&memberRole); err != nil {
			return ErrNotOwned
		}
		if memberRole != "ADMIN" && memberRole != "DEVELOPER" {
			return ErrNotOwned
		}
	}

	if _, err = tx.ExecContext(
		ctx,
		`
		DELETE FROM project_conversations
		WHERE conversation_id = ?
		`,
		conversationID,
	); err != nil {
		return err
	}

	if _, err = tx.ExecContext(
		ctx,
		`
		INSERT INTO project_conversations(
			project_id,
			conversation_id
		)
		VALUES(
			?,
			?
		)
		`,
		projectID,
		conversationID,
	); err != nil {
		return err
	}

	if _, err = tx.ExecContext(
		ctx,
		`
		UPDATE projects
		SET updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		`,
		projectID,
	); err != nil {
		return err
	}

	return tx.Commit()
}

func (r *MySQL) RemoveConversationFromProject(
	ctx context.Context,
	uid int64,
	conversationID int64,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		DELETE pc
		FROM project_conversations pc
		INNER JOIN conversations c
			ON c.id = pc.conversation_id
		WHERE pc.conversation_id = ?
		  AND c.user_id = ?
		`,
		conversationID,
		uid,
	)

	if err != nil {
		return err
	}

	_, err =
		result.RowsAffected()

	return err
}
