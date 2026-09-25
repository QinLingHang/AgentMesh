package repository

import (
	"context"
	"database/sql"
	"errors"

	"example.com/agentmesh-control-plane/internal/model"
)

type knowledgeScanner interface {
	Scan(...any) error
}

func scanKnowledgeBase(
	scanner knowledgeScanner,
) (*model.KnowledgeBase, error) {
	var base model.KnowledgeBase

	err := scanner.Scan(
		&base.ID,
		&base.UserID,
		&base.Name,
		&base.Description,
		&base.Scope,
		&base.ProjectID,
		&base.ProjectName,
		&base.IsDefault,
		&base.FileCount,
		&base.ReadyFileCount,
		&base.PendingFileCount,
		&base.ErrorFileCount,
		&base.CreatedAt,
		&base.UpdatedAt,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &base, nil
}

const knowledgeBaseSelect = `
	SELECT
		kb.id,
		kb.user_id,
		kb.name,
		kb.description,
		kb.scope,
		kb.project_id,
		COALESCE(p.name, ''),
		kb.is_default,
		COUNT(f.id) AS file_count,
		COALESCE(SUM(CASE WHEN f.status = 'READY' THEN 1 ELSE 0 END), 0) AS ready_file_count,
		COALESCE(SUM(CASE WHEN f.status NOT IN ('READY', 'ERROR') THEN 1 ELSE 0 END), 0) AS pending_file_count,
		COALESCE(SUM(CASE WHEN f.status = 'ERROR' THEN 1 ELSE 0 END), 0) AS error_file_count,
		kb.created_at,
		kb.updated_at
	FROM knowledge_bases kb
	LEFT JOIN projects p
		ON p.id = kb.project_id
	   AND p.user_id = kb.user_id
	LEFT JOIN project_knowledge_files f
		ON f.knowledge_base_id = kb.id
	   AND f.user_id = kb.user_id
`

const knowledgeBaseGroup = `
	GROUP BY
		kb.id,
		kb.user_id,
		kb.name,
		kb.description,
		kb.scope,
		kb.project_id,
		p.name,
		kb.is_default,
		kb.created_at,
		kb.updated_at
`

func (r *MySQL) EnsureDefaultGlobalKnowledgeBase(
	ctx context.Context,
	uid int64,
) (*model.KnowledgeBase, error) {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO knowledge_bases(
			user_id,
			identity_key,
			name,
			description,
			scope,
			project_id,
			is_default
		)
		VALUES(?, 'global:default', '全局知识库', '普通会话默认可用的个人通用知识。', 'GLOBAL', NULL, 1)
		ON DUPLICATE KEY UPDATE updated_at = updated_at
		`,
		uid,
	)
	if err != nil {
		return nil, err
	}

	return scanKnowledgeBase(
		r.db.QueryRowContext(
			ctx,
			knowledgeBaseSelect+`
			WHERE kb.user_id = ?
			  AND kb.identity_key = 'global:default'
			`+knowledgeBaseGroup+`
			LIMIT 1
			`,
			uid,
		),
	)
}

func (r *MySQL) EnsureDefaultProjectKnowledgeBase(
	ctx context.Context,
	uid int64,
	projectID int64,
	projectName string,
) (*model.KnowledgeBase, error) {
	identity := "project:" + formatInt64(projectID) + ":default"

	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO knowledge_bases(
			user_id,
			identity_key,
			name,
			description,
			scope,
			project_id,
			is_default
		)
		VALUES(?, ?, ?, '当前项目专属知识。', 'PROJECT', ?, 1)
		ON DUPLICATE KEY UPDATE
			name = VALUES(name),
			updated_at = updated_at
		`,
		uid,
		identity,
		projectName+" · 项目知识",
		projectID,
	)
	if err != nil {
		return nil, err
	}

	return scanKnowledgeBase(
		r.db.QueryRowContext(
			ctx,
			knowledgeBaseSelect+`
			WHERE kb.user_id = ?
			  AND kb.identity_key = ?
			`+knowledgeBaseGroup+`
			LIMIT 1
			`,
			uid,
			identity,
		),
	)
}

func formatInt64(value int64) string {
	if value == 0 {
		return "0"
	}

	negative := value < 0
	if negative {
		value = -value
	}

	var buffer [20]byte
	position := len(buffer)

	for value > 0 {
		position--
		buffer[position] = byte('0' + value%10)
		value /= 10
	}

	if negative {
		position--
		buffer[position] = '-'
	}

	return string(buffer[position:])
}

func (r *MySQL) ListKnowledgeBases(
	ctx context.Context,
	uid int64,
) ([]model.KnowledgeBase, error) {
	rows, err := r.db.QueryContext(
		ctx,
		knowledgeBaseSelect+`
		WHERE (
			kb.scope = 'GLOBAL' AND kb.user_id = ?
			OR kb.scope = 'PROJECT' AND EXISTS (
				SELECT 1 FROM projects project_row
				WHERE project_row.id=kb.project_id AND (project_row.user_id=? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=project_row.id AND pm.user_id=?))
			)
		)
		`+knowledgeBaseGroup+`
		ORDER BY
			CASE kb.scope WHEN 'GLOBAL' THEN 0 ELSE 1 END,
			kb.is_default DESC,
			kb.updated_at DESC,
			kb.id DESC
		`,
		uid,
		uid,
		uid,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []model.KnowledgeBase{}
	for rows.Next() {
		base, err := scanKnowledgeBase(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *base)
	}

	return result, rows.Err()
}

func (r *MySQL) KnowledgeBaseByID(
	ctx context.Context,
	uid int64,
	baseID int64,
) (*model.KnowledgeBase, error) {
	return scanKnowledgeBase(
		r.db.QueryRowContext(
			ctx,
			knowledgeBaseSelect+`
			WHERE kb.id = ?
			  AND (
				kb.scope='GLOBAL' AND kb.user_id=?
				OR kb.scope='PROJECT' AND EXISTS (SELECT 1 FROM projects project_row WHERE project_row.id=kb.project_id AND (project_row.user_id=? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=project_row.id AND pm.user_id=?)))
			  )
			`+knowledgeBaseGroup+`
			LIMIT 1
			`,
			baseID,
			uid,
			uid,
			uid,
		),
	)
}

func (r *MySQL) CreateKnowledgeBase(
	ctx context.Context,
	uid int64,
	identityKey string,
	name string,
	description string,
	scope model.KnowledgeBaseScope,
	projectID *int64,
) (*model.KnowledgeBase, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO knowledge_bases(
			user_id,
			identity_key,
			name,
			description,
			scope,
			project_id,
			is_default
		)
		VALUES(?, ?, ?, ?, ?, ?, 0)
		`,
		uid,
		identityKey,
		name,
		description,
		scope,
		projectID,
	)
	if err != nil {
		return nil, err
	}

	id, err := result.LastInsertId()
	if err != nil {
		return nil, err
	}

	return r.KnowledgeBaseByID(ctx, uid, id)
}

func (r *MySQL) UpdateKnowledgeBase(
	ctx context.Context,
	uid int64,
	baseID int64,
	name string,
	description string,
) (*model.KnowledgeBase, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE knowledge_bases
		SET
			name = ?,
			description = ?,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		name,
		description,
		baseID,
		uid,
	)
	if err != nil {
		return nil, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return nil, err
	}
	if affected == 0 {
		return nil, nil
	}

	return r.KnowledgeBaseByID(ctx, uid, baseID)
}

func (r *MySQL) DeleteKnowledgeBase(
	ctx context.Context,
	uid int64,
	baseID int64,
) (bool, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM knowledge_bases
		WHERE id = ?
		  AND user_id = ?
		  AND is_default = 0
		`,
		baseID,
		uid,
	)
	if err != nil {
		return false, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected == 1, nil
}

func scanKnowledgeFile(
	scanner knowledgeScanner,
) (*model.KnowledgeFile, error) {
	var file model.KnowledgeFile

	err := scanner.Scan(
		&file.ID,
		&file.KnowledgeBaseID,
		&file.KnowledgeBaseName,
		&file.Scope,
		&file.ProjectID,
		&file.ProjectName,
		&file.UserID,
		&file.OriginalName,
		&file.MediaType,
		&file.Extension,
		&file.SizeBytes,
		&file.ChecksumSHA256,
		&file.StorageKey,
		&file.Status,
		&file.ChunkCount,
		&file.TextChunkCount,
		&file.VisualEvidenceCount,
		&file.PageCount,
		&file.VisualStatus,
		&file.VisualErrorMessage,
		&file.ErrorMessage,
		&file.IndexedAt,
		&file.CreatedAt,
		&file.UpdatedAt,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &file, nil
}

const knowledgeFileSelect = `
	SELECT
		f.id,
		f.knowledge_base_id,
		kb.name,
		kb.scope,
		f.project_id,
		COALESCE(p.name, ''),
		f.user_id,
		f.original_name,
		f.media_type,
		f.extension,
		f.size_bytes,
		f.checksum_sha256,
		f.storage_key,
		f.status,
		f.chunk_count,
		f.text_chunk_count,
		f.visual_evidence_count,
		f.page_count,
		f.visual_status,
		f.visual_error_message,
		f.error_message,
		f.indexed_at,
		f.created_at,
		f.updated_at
	FROM project_knowledge_files f
	INNER JOIN knowledge_bases kb
		ON kb.id = f.knowledge_base_id
	   AND kb.user_id = f.user_id
	LEFT JOIN projects p
		ON p.id = f.project_id
	   AND p.user_id = f.user_id
`

func (r *MySQL) CreateKnowledgeFile(
	ctx context.Context,
	file model.KnowledgeFile,
) (*model.KnowledgeFile, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO project_knowledge_files(
			project_id,
			knowledge_base_id,
			user_id,
			original_name,
			media_type,
			extension,
			size_bytes,
			checksum_sha256,
			storage_key,
			status,
			chunk_count
		)
		VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
		file.ProjectID,
		file.KnowledgeBaseID,
		file.UserID,
		file.OriginalName,
		file.MediaType,
		file.Extension,
		file.SizeBytes,
		file.ChecksumSHA256,
		file.StorageKey,
		file.Status,
		file.ChunkCount,
	)
	if err != nil {
		return nil, err
	}

	id, err := result.LastInsertId()
	if err != nil {
		return nil, err
	}

	return r.KnowledgeFileByID(ctx, file.UserID, id)
}

func (r *MySQL) ListKnowledgeFilesByBase(
	ctx context.Context,
	uid int64,
	baseID int64,
) ([]model.KnowledgeFile, error) {
	rows, err := r.db.QueryContext(
		ctx,
		knowledgeFileSelect+`
		WHERE f.knowledge_base_id = ?
		  AND (
			kb.scope='GLOBAL' AND kb.user_id=?
			OR kb.scope='PROJECT' AND EXISTS (SELECT 1 FROM projects project_row WHERE project_row.id=kb.project_id AND (project_row.user_id=? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=project_row.id AND pm.user_id=?)))
		  )
		ORDER BY f.created_at DESC, f.id DESC
		`,
		baseID,
		uid,
		uid,
		uid,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []model.KnowledgeFile{}
	for rows.Next() {
		file, err := scanKnowledgeFile(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *file)
	}

	return result, rows.Err()
}

func (r *MySQL) ListKnowledgeFilesByProject(
	ctx context.Context,
	uid int64,
	projectID int64,
) ([]model.KnowledgeFile, error) {
	rows, err := r.db.QueryContext(
		ctx,
		knowledgeFileSelect+`
		WHERE kb.scope = 'PROJECT'
		  AND kb.project_id = ?
		  AND EXISTS (SELECT 1 FROM projects project_row WHERE project_row.id=kb.project_id AND (project_row.user_id=? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=project_row.id AND pm.user_id=?)))
		ORDER BY f.created_at DESC, f.id DESC
		`,
		projectID,
		uid,
		uid,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []model.KnowledgeFile{}
	for rows.Next() {
		file, err := scanKnowledgeFile(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *file)
	}

	return result, rows.Err()
}

func (r *MySQL) ListAllKnowledgeFiles(
	ctx context.Context,
	uid int64,
) ([]model.KnowledgeFile, error) {
	rows, err := r.db.QueryContext(
		ctx,
		knowledgeFileSelect+`
		WHERE f.user_id = ?
		ORDER BY f.updated_at DESC, f.id DESC
		`,
		uid,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []model.KnowledgeFile{}
	for rows.Next() {
		file, err := scanKnowledgeFile(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *file)
	}

	return result, rows.Err()
}

func (r *MySQL) KnowledgeFileByID(
	ctx context.Context,
	uid int64,
	fileID int64,
) (*model.KnowledgeFile, error) {
	return scanKnowledgeFile(
		r.db.QueryRowContext(
			ctx,
			knowledgeFileSelect+`
			WHERE f.id = ?
			  AND (
				kb.scope='GLOBAL' AND f.user_id=?
				OR kb.scope='PROJECT' AND EXISTS (SELECT 1 FROM projects project_row WHERE project_row.id=kb.project_id AND (project_row.user_id=? OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=project_row.id AND pm.user_id=?)))
			  )
			LIMIT 1
			`,
			fileID,
			uid,
			uid,
			uid,
		),
	)
}

func (r *MySQL) DeleteKnowledgeFile(
	ctx context.Context,
	uid int64,
	fileID int64,
) (bool, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		DELETE f FROM project_knowledge_files f
		LEFT JOIN knowledge_bases kb ON kb.id=f.knowledge_base_id
		WHERE f.id = ?
		  AND (
			f.user_id = ?
			OR kb.scope='PROJECT' AND EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=kb.project_id AND pm.user_id=? AND pm.role IN ('OWNER','ADMIN','DEVELOPER'))
		  )
		`,
		fileID,
		uid,
		uid,
	)
	if err != nil {
		return false, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected == 1, nil
}

func (r *MySQL) ListBoundGlobalKnowledgeBases(
	ctx context.Context,
	uid int64,
	projectID int64,
) ([]model.KnowledgeBase, error) {
	rows, err := r.db.QueryContext(
		ctx,
		knowledgeBaseSelect+`
		INNER JOIN project_global_knowledge_bindings b
			ON b.knowledge_base_id = kb.id
		   AND b.user_id = kb.user_id
		WHERE kb.user_id = ?
		  AND kb.scope = 'GLOBAL'
		  AND b.project_id = ?
		`+knowledgeBaseGroup+`
		ORDER BY kb.is_default DESC, kb.updated_at DESC, kb.id DESC
		`,
		uid,
		projectID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []model.KnowledgeBase{}
	for rows.Next() {
		base, err := scanKnowledgeBase(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *base)
	}

	return result, rows.Err()
}

func (r *MySQL) BindGlobalKnowledgeBase(
	ctx context.Context,
	uid int64,
	projectID int64,
	baseID int64,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO project_global_knowledge_bindings(
			project_id,
			knowledge_base_id,
			user_id
		)
		SELECT p.id, kb.id, ?
		FROM projects p
		INNER JOIN knowledge_bases kb
			ON kb.id = ?
		   AND kb.user_id = ?
		   AND kb.scope = 'GLOBAL'
		WHERE p.id = ?
		  AND p.user_id = ?
		ON DUPLICATE KEY UPDATE
			user_id = VALUES(user_id)
		`,
		uid,
		baseID,
		uid,
		projectID,
		uid,
	)
	if err != nil {
		return err
	}

	_ = result

	return nil
}

func (r *MySQL) UnbindGlobalKnowledgeBase(
	ctx context.Context,
	uid int64,
	projectID int64,
	baseID int64,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM project_global_knowledge_bindings
		WHERE project_id = ?
		  AND knowledge_base_id = ?
		  AND user_id = ?
		`,
		projectID,
		baseID,
		uid,
	)

	return err
}

// =========================================================
// Knowledge Index Lifecycle
// =========================================================

func (r *MySQL) PrepareKnowledgeFileReindex(
	ctx context.Context,
	uid int64,
	fileID int64,
) (bool, error) {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE project_knowledge_files
		SET
			status = 'UPLOADED',
			chunk_count = 0,
			text_chunk_count = 0,
			visual_evidence_count = 0,
			page_count = 0,
			visual_status = 'not_applicable',
			visual_error_message = NULL,
			error_message = NULL,
			indexed_at = NULL,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		fileID,
		uid,
	)
	if err != nil {
		return false, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected == 1, nil
}

func (r *MySQL) MarkKnowledgeFileIndexing(
	ctx context.Context,
	uid int64,
	fileID int64,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		UPDATE project_knowledge_files
		SET
			status = 'INDEXING',
			chunk_count = 0,
			text_chunk_count = 0,
			visual_evidence_count = 0,
			page_count = 0,
			visual_status = 'not_applicable',
			visual_error_message = NULL,
			error_message = NULL,
			indexed_at = NULL,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		fileID,
		uid,
	)

	return err
}

func (r *MySQL) CompleteKnowledgeFileIndex(
	ctx context.Context,
	uid int64,
	fileID int64,
	result model.KnowledgeIndexResult,
) error {
	visualStatus := result.VisualStatus
	if visualStatus == "" {
		visualStatus = "not_applicable"
	}
	var visualError any
	if result.VisualError != "" {
		visualError = result.VisualError
	}
	_, err := r.db.ExecContext(
		ctx,
		`
		UPDATE project_knowledge_files
		SET
			status = 'READY',
			chunk_count = ?,
			text_chunk_count = ?,
			visual_evidence_count = ?,
			page_count = ?,
			visual_status = ?,
			visual_error_message = ?,
			error_message = NULL,
			indexed_at = CURRENT_TIMESTAMP(6),
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		result.ChunkCount,
		result.TextChunkCount,
		result.VisualEvidenceCount,
		result.PageCount,
		visualStatus,
		visualError,
		fileID,
		uid,
	)

	return err
}

func (r *MySQL) FailKnowledgeFileIndex(
	ctx context.Context,
	uid int64,
	fileID int64,
	message string,
) error {
	if len(message) > 900 {
		message = message[:900]
	}

	_, err := r.db.ExecContext(
		ctx,
		`
		UPDATE project_knowledge_files
		SET
			status = 'ERROR',
			chunk_count = 0,
			text_chunk_count = 0,
			visual_evidence_count = 0,
			page_count = 0,
			visual_status = 'failed',
			visual_error_message = NULL,
			error_message = ?,
			indexed_at = NULL,
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		message,
		fileID,
		uid,
	)

	return err
}

// ResolveRuntimeKnowledgeScope returns the only KnowledgeBase IDs that the
// Python Runtime is allowed to search for this user/conversation.
//
// Non-project conversation:
//
//	all GLOBAL bases owned by the user.
//
// Project conversation:
//
//	PROJECT bases for that Project
//	+ GLOBAL bases explicitly bound to that Project.
func (r *MySQL) ResolveRuntimeKnowledgeScope(
	ctx context.Context,
	uid int64,
	conversationID *int64,
) (*model.RuntimeKnowledgeScope, error) {
	scope := &model.RuntimeKnowledgeScope{
		UserID:           uid,
		ConversationID:   conversationID,
		Mode:             "GLOBAL",
		KnowledgeBaseIDs: []int64{},
	}

	var projectID *int64

	if conversationID != nil {
		var project sql.NullInt64

		err := r.db.QueryRowContext(
			ctx,
			`
			SELECT p.id
			FROM conversations c
			LEFT JOIN project_conversations pc
				ON pc.conversation_id = c.id
			LEFT JOIN projects p
				ON p.id = pc.project_id
			   AND p.user_id = c.user_id
			WHERE c.id = ?
			  AND c.user_id = ?
			LIMIT 1
			`,
			*conversationID,
			uid,
		).Scan(&project)

		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotOwned
		}
		if err != nil {
			return nil, err
		}

		if project.Valid {
			value := project.Int64
			projectID = &value
			scope.ProjectID = &value
			scope.Mode = "PROJECT"
		}
	}

	var (
		rows *sql.Rows
		err  error
	)

	if projectID == nil {
		rows, err = r.db.QueryContext(
			ctx,
			`
			SELECT kb.id
			FROM knowledge_bases kb
			WHERE kb.user_id = ?
			  AND kb.scope = 'GLOBAL'
			ORDER BY kb.id ASC
			`,
			uid,
		)
	} else {
		rows, err = r.db.QueryContext(
			ctx,
			`
			SELECT DISTINCT kb.id
			FROM knowledge_bases kb
			WHERE kb.user_id = ?
			  AND (
				(kb.scope = 'PROJECT' AND kb.project_id = ?)
				OR
				(
					kb.scope = 'GLOBAL'
					AND EXISTS (
						SELECT 1
						FROM project_global_knowledge_bindings b
						WHERE b.project_id = ?
						  AND b.knowledge_base_id = kb.id
						  AND b.user_id = ?
					)
				)
			  )
			ORDER BY kb.id ASC
			`,
			uid,
			*projectID,
			*projectID,
			uid,
		)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		scope.KnowledgeBaseIDs = append(scope.KnowledgeBaseIDs, id)
	}

	if err = rows.Err(); err != nil {
		return nil, err
	}

	return scope, nil
}
