package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"

	mysqlDriver "github.com/go-sql-driver/mysql"
)

type MySQL struct {
	db *sql.DB
}

func NewMySQL(
	db *sql.DB,
) *MySQL {
	return &MySQL{
		db: db,
	}
}

type scanner interface {
	Scan(
		...any,
	) error
}

// =========================================================
// User
// =========================================================

func scanUser(
	s scanner,
) (*model.User, error) {
	var u model.User

	err := s.Scan(
		&u.ID,
		&u.Email,
		&u.PasswordHash,
		&u.DisplayName,
		&u.Status,
		&u.CreatedAt,
		&u.UpdatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, nil
	}

	return &u, err
}

func (r *MySQL) CreateUser(
	ctx context.Context,
	email string,
	hash string,
	name string,
) (*model.User, error) {
	res, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO users(
			email,
			password_hash,
			display_name,
			status
		)
		VALUES(
			?,
			?,
			?,
			'ACTIVE'
		)
		`,
		email,
		hash,
		name,
	)

	if err != nil {
		var mysqlErr *mysqlDriver.MySQLError

		if errors.As(
			err,
			&mysqlErr,
		) &&
			mysqlErr.Number == 1062 {
			return nil, ErrEmailExists
		}

		return nil, err
	}

	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}

	return r.UserByID(
		ctx,
		id,
	)
}

func (r *MySQL) UserByEmail(
	ctx context.Context,
	email string,
) (*model.User, error) {
	return scanUser(
		r.db.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				email,
				password_hash,
				display_name,
				status,
				created_at,
				updated_at
			FROM users
			WHERE email = ?
			LIMIT 1
			`,
			email,
		),
	)
}

func (r *MySQL) UserByID(
	ctx context.Context,
	id int64,
) (*model.User, error) {
	return scanUser(
		r.db.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				email,
				password_hash,
				display_name,
				status,
				created_at,
				updated_at
			FROM users
			WHERE id = ?
			LIMIT 1
			`,
			id,
		),
	)
}

// =========================================================
// Refresh Token
// =========================================================

func (r *MySQL) CreateRefresh(
	ctx context.Context,
	uid int64,
	hash string,
	expires time.Time,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO refresh_tokens(
			user_id,
			token_hash,
			expires_at
		)
		VALUES(
			?,
			?,
			?
		)
		`,
		uid,
		hash,
		expires.UTC(),
	)

	return err
}

func (r *MySQL) RotateRefresh(
	ctx context.Context,
	oldHash string,
	newHash string,
	expires time.Time,
) (int64, error) {
	tx, err := r.db.BeginTx(
		ctx,
		nil,
	)

	if err != nil {
		return 0, err
	}

	defer func() {
		_ = tx.Rollback()
	}()

	var uid int64

	err = tx.QueryRowContext(
		ctx,
		`
		SELECT
			rt.user_id
		FROM refresh_tokens rt
		INNER JOIN users u
			ON u.id = rt.user_id
		WHERE rt.token_hash = ?
		  AND rt.revoked_at IS NULL
		  AND rt.expires_at > UTC_TIMESTAMP(6)
		  AND u.status = 'ACTIVE'
		LIMIT 1
		FOR UPDATE
		`,
		oldHash,
	).Scan(
		&uid,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return 0, ErrInvalidRefreshToken
	}

	if err != nil {
		return 0, err
	}

	res, err := tx.ExecContext(
		ctx,
		`
		UPDATE refresh_tokens
		SET revoked_at = UTC_TIMESTAMP(6)
		WHERE token_hash = ?
		  AND revoked_at IS NULL
		`,
		oldHash,
	)

	if err != nil {
		return 0, err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return 0, err
	}

	if affected != 1 {
		return 0, ErrInvalidRefreshToken
	}

	if _, err = tx.ExecContext(
		ctx,
		`
		INSERT INTO refresh_tokens(
			user_id,
			token_hash,
			expires_at
		)
		VALUES(
			?,
			?,
			?
		)
		`,
		uid,
		newHash,
		expires.UTC(),
	); err != nil {
		return 0, err
	}

	if err = tx.Commit(); err != nil {
		return 0, err
	}

	return uid, nil
}

func (r *MySQL) RevokeRefresh(
	ctx context.Context,
	hash string,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		UPDATE refresh_tokens
		SET revoked_at = UTC_TIMESTAMP(6)
		WHERE token_hash = ?
		  AND revoked_at IS NULL
		`,
		hash,
	)

	return err
}

// =========================================================
// Conversation
// =========================================================

func scanConversation(
	s scanner,
) (*model.Conversation, error) {
	var conversation model.Conversation

	var lastMessageAt sql.NullTime

	err := s.Scan(
		&conversation.ID,
		&conversation.UserID,
		&conversation.Title,
		&lastMessageAt,
		&conversation.CreatedAt,
		&conversation.UpdatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, nil
	}

	if err != nil {
		return nil, err
	}

	if lastMessageAt.Valid {
		value := lastMessageAt.Time

		conversation.LastMessageAt = &value
	}

	return &conversation, nil
}

func (r *MySQL) CreateConversation(
	ctx context.Context,
	uid int64,
	title string,
) (*model.Conversation, error) {
	res, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO conversations(
			user_id,
			title
		)
		VALUES(
			?,
			?
		)
		`,
		uid,
		title,
	)

	if err != nil {
		return nil, err
	}

	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}

	return r.ConversationByID(
		ctx,
		uid,
		id,
	)
}

func (r *MySQL) ConversationByID(
	ctx context.Context,
	uid int64,
	id int64,
) (*model.Conversation, error) {
	return scanConversation(
		r.db.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				user_id,
				title,
				last_message_at,
				created_at,
				updated_at
			FROM conversations
			WHERE id = ?
			  AND user_id = ?
			LIMIT 1
			`,
			id,
			uid,
		),
	)
}

func (r *MySQL) ListConversations(
	ctx context.Context,
	uid int64,
	limit int,
) ([]model.Conversation, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			user_id,
			title,
			last_message_at,
			created_at,
			updated_at
		FROM conversations
		WHERE user_id = ?
		ORDER BY
			updated_at DESC,
			id DESC
		LIMIT ?
		`,
		uid,
		limit,
	)

	if err != nil {
		return nil, err
	}

	defer rows.Close()

	result := []model.Conversation{}

	for rows.Next() {
		conversation, err := scanConversation(
			rows,
		)

		if err != nil {
			return nil, err
		}

		result = append(
			result,
			*conversation,
		)
	}

	return result, rows.Err()
}

func (r *MySQL) DeleteConversation(
	ctx context.Context,
	uid int64,
	id int64,
) (bool, error) {
	res, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM conversations
		WHERE id = ?
		  AND user_id = ?
		`,
		id,
		uid,
	)

	if err != nil {
		return false, err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected > 0, nil
}

// =========================================================
// Message
// =========================================================

func scanMessage(
	s scanner,
) (*model.Message, error) {
	var message model.Message

	var requestID sql.NullString

	var metadata []byte

	err := s.Scan(
		&message.ID,
		&message.ConversationID,
		&message.Role,
		&message.Content,
		&message.Status,
		&requestID,
		&metadata,
		&message.CreatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, nil
	}

	if err != nil {
		return nil, err
	}

	if requestID.Valid {
		value := requestID.String

		message.RequestID = &value
	}

	if len(
		metadata,
	) > 0 {
		_ = json.Unmarshal(
			metadata,
			&message.Metadata,
		)
	}

	return &message, nil
}

func (r *MySQL) CreateMessage(
	ctx context.Context,
	uid int64,
	conversationID int64,
	role string,
	content string,
	status string,
	requestID string,
	metadata map[string]any,
) (*model.Message, error) {
	tx, err := r.db.BeginTx(
		ctx,
		nil,
	)

	if err != nil {
		return nil, err
	}

	defer func() {
		_ = tx.Rollback()
	}()

	// =====================================================
	// Tenant Ownership Check
	// =====================================================

	var ownedID int64

	err = tx.QueryRowContext(
		ctx,
		`
		SELECT id
		FROM conversations
		WHERE id = ?
		  AND user_id = ?
		LIMIT 1
		FOR UPDATE
		`,
		conversationID,
		uid,
	).Scan(
		&ownedID,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, ErrNotOwned
	}

	if err != nil {
		return nil, err
	}

	var requestValue any

	if requestID != "" {
		requestValue = requestID
	}

	var metadataValue any

	if metadata != nil {
		data, err := json.Marshal(
			metadata,
		)

		if err != nil {
			return nil, err
		}

		metadataValue = string(
			data,
		)
	}

	res, err := tx.ExecContext(
		ctx,
		`
		INSERT INTO messages(
			conversation_id,
			role,
			content,
			status,
			request_id,
			metadata_json
		)
		VALUES(
			?,
			?,
			?,
			?,
			?,
			?
		)
		`,
		conversationID,
		role,
		content,
		status,
		requestValue,
		metadataValue,
	)

	if err != nil {
		return nil, err
	}

	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}

	if _, err = tx.ExecContext(
		ctx,
		`
		UPDATE conversations
		SET
			last_message_at = CURRENT_TIMESTAMP(6),
			updated_at = CURRENT_TIMESTAMP(6)
		WHERE id = ?
		  AND user_id = ?
		`,
		conversationID,
		uid,
	); err != nil {
		return nil, err
	}

	message, err := scanMessage(
		tx.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				conversation_id,
				role,
				content,
				status,
				request_id,
				metadata_json,
				created_at
			FROM messages
			WHERE id = ?
			`,
			id,
		),
	)

	if err != nil {
		return nil, err
	}

	if err = tx.Commit(); err != nil {
		return nil, err
	}

	return message, nil
}

func (r *MySQL) ListMessages(
	ctx context.Context,
	uid int64,
	conversationID int64,
	limit int,
) ([]model.Message, error) {
	var ownedID int64

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT id
		FROM conversations
		WHERE id = ?
		  AND user_id = ?
		LIMIT 1
		`,
		conversationID,
		uid,
	).Scan(
		&ownedID,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, ErrNotOwned
	}

	if err != nil {
		return nil, err
	}

	// List the most recent N messages, but return them in chronological
	// order.  `ORDER BY id ASC LIMIT N` returns the oldest N rows and caused
	// long conversations to feed stale context into follow-up turns.
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			conversation_id,
			role,
			content,
			status,
			request_id,
			metadata_json,
			created_at
		FROM (
			SELECT
				id,
				conversation_id,
				role,
				content,
				status,
				request_id,
				metadata_json,
				created_at
			FROM messages
			WHERE conversation_id = ?
			ORDER BY id DESC
			LIMIT ?
		) AS recent_messages
		ORDER BY id ASC
		`,
		conversationID,
		limit,
	)

	if err != nil {
		return nil, err
	}

	defer rows.Close()

	result := []model.Message{}

	for rows.Next() {
		message, err := scanMessage(
			rows,
		)

		if err != nil {
			return nil, err
		}

		result = append(
			result,
			*message,
		)
	}

	return result, rows.Err()
}

// ListMessagesBefore pages the durable conversation log without deleting or
// truncating older rows. Cursoring by the immutable message id keeps pagination
// stable while new turns are appended concurrently. The query fetches limit+1
// rows so hasMore is authoritative without a separate COUNT(*) round-trip.
func (r *MySQL) ListMessagesBefore(
	ctx context.Context,
	uid int64,
	conversationID int64,
	beforeID int64,
	limit int,
) ([]model.Message, bool, error) {
	var ownedID int64
	if err := r.db.QueryRowContext(
		ctx,
		`SELECT id FROM conversations WHERE id = ? AND user_id = ? LIMIT 1`,
		conversationID,
		uid,
	).Scan(&ownedID); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, false, ErrNotOwned
		}
		return nil, false, err
	}

	if limit <= 0 {
		return []model.Message{}, false, nil
	}

	query := `
		SELECT id, conversation_id, role, content, status, request_id, metadata_json, created_at
		FROM messages
		WHERE conversation_id = ?
	`
	args := []any{conversationID}
	if beforeID > 0 {
		query += ` AND id < ?`
		args = append(args, beforeID)
	}
	query += ` ORDER BY id DESC LIMIT ?`
	args = append(args, limit+1)

	rows, err := r.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()

	newestFirst := make([]model.Message, 0, limit+1)
	for rows.Next() {
		message, scanErr := scanMessage(rows)
		if scanErr != nil {
			return nil, false, scanErr
		}
		newestFirst = append(newestFirst, *message)
	}
	if err := rows.Err(); err != nil {
		return nil, false, err
	}

	hasMore := len(newestFirst) > limit
	if hasMore {
		newestFirst = newestFirst[:limit]
	}

	// API consumers render each page chronologically. Older pages are prepended
	// client-side, so the full thread remains first-turn -> latest-turn.
	for left, right := 0, len(newestFirst)-1; left < right; left, right = left+1, right-1 {
		newestFirst[left], newestFirst[right] = newestFirst[right], newestFirst[left]
	}

	return newestFirst, hasMore, nil
}

// =========================================================
// Agent
// =========================================================

func scanAgent(
	s scanner,
) (*model.Agent, error) {
	var agent model.Agent

	var capabilities []byte

	err := s.Scan(
		&agent.ID,
		&agent.UserID,
		&agent.Name,
		&agent.Description,
		&agent.Endpoint,
		&agent.Protocol,
		&capabilities,
		&agent.Provider,
		&agent.ModelName,
		&agent.QualityScore,
		&agent.AvgLatencyMS,
		&agent.AvgCost,
		&agent.SuccessRate,
		&agent.FailureRate,
		&agent.CurrentLoad,
		&agent.Status,
		&agent.CreatedAt,
		&agent.UpdatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, nil
	}

	if err != nil {
		return nil, err
	}

	if err = json.Unmarshal(
		capabilities,
		&agent.Capabilities,
	); err != nil {
		return nil, err
	}

	if agent.CapabilityProfiles == nil {
		agent.CapabilityProfiles = []model.AgentCapabilityProfile{}
	}

	return &agent, nil
}

// =========================================================
// Capability Profile Loader
//
// agents
// +
// agent_capability_profiles
//
// -> Python AgentProfile.capabilityProfiles
// =========================================================

func (r *MySQL) loadAgentCapabilityProfiles(
	ctx context.Context,
	uid int64,
	agents []model.Agent,
) error {
	if len(
		agents,
	) == 0 {
		return nil
	}

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			p.agent_id,
			p.capability,
			p.quality_score,
			p.avg_latency_ms,
			p.avg_cost,
			p.success_rate,
			p.failure_rate,
			p.sample_count
		FROM agent_capability_profiles p
		INNER JOIN agents a
			ON a.id = p.agent_id
		WHERE a.user_id = ?
		  AND a.status = 'ACTIVE'
		ORDER BY
			p.agent_id ASC,
			p.capability ASC
		`,
		uid,
	)

	if err != nil {
		return err
	}

	defer rows.Close()

	profilesByAgent :=
		make(
			map[int64][]model.AgentCapabilityProfile,
		)

	for rows.Next() {
		var agentID int64

		var profile model.AgentCapabilityProfile

		if err = rows.Scan(
			&agentID,
			&profile.Capability,
			&profile.QualityScore,
			&profile.AvgLatencyMS,
			&profile.AvgCost,
			&profile.SuccessRate,
			&profile.FailureRate,
			&profile.SampleCount,
		); err != nil {
			return err
		}

		profilesByAgent[agentID] = append(
			profilesByAgent[agentID],
			profile,
		)
	}

	if err = rows.Err(); err != nil {
		return err
	}

	// 必须通过索引修改 slice 中真正的元素。
	//
	// 如果写：
	//
	// for _, agent := range agents
	//
	// agent 只是 struct 副本，
	// 不会写回原 slice。
	for i := range agents {
		profiles :=
			profilesByAgent[agents[i].ID]

		if profiles == nil {
			profiles =
				[]model.AgentCapabilityProfile{}
		}

		agents[i].CapabilityProfiles =
			profiles
	}

	return nil
}

func (r *MySQL) CreateAgent(
	ctx context.Context,
	uid int64,
	agent model.Agent,
) (*model.Agent, error) {
	capabilities, err := json.Marshal(
		agent.Capabilities,
	)

	if err != nil {
		return nil, err
	}

	res, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO agents(
			user_id,
			name,
			description,
			endpoint,
			protocol,
			capabilities_json,
			provider,
			model_name,
			quality_score,
			avg_latency_ms,
			avg_cost,
			success_rate,
			failure_rate,
			current_load,
			status
		)
		VALUES(
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			'ACTIVE'
		)
		`,
		uid,
		agent.Name,
		agent.Description,
		agent.Endpoint,
		agent.Protocol,
		string(
			capabilities,
		),
		agent.Provider,
		agent.ModelName,
		agent.QualityScore,
		agent.AvgLatencyMS,
		agent.AvgCost,
		agent.SuccessRate,
		agent.FailureRate,
		agent.CurrentLoad,
	)

	if err != nil {
		return nil, err
	}

	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}

	return scanAgent(
		r.db.QueryRowContext(
			ctx,
			`
			SELECT
				id,
				user_id,
				name,
				description,
				endpoint,
				protocol,
				capabilities_json,
				provider,
				model_name,
				quality_score,
				avg_latency_ms,
				avg_cost,
				success_rate,
				failure_rate,
				current_load,
				status,
				created_at,
				updated_at
			FROM agents
			WHERE id = ?
			  AND user_id = ?
			`,
			id,
			uid,
		),
	)
}

func (r *MySQL) ListAgents(
	ctx context.Context,
	uid int64,
) ([]model.Agent, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			user_id,
			name,
			description,
			endpoint,
			protocol,
			capabilities_json,
			provider,
			model_name,
			quality_score,
			avg_latency_ms,
			avg_cost,
			success_rate,
			failure_rate,
			current_load,
			status,
			created_at,
			updated_at
		FROM agents
		WHERE user_id = ?
		  AND status = 'ACTIVE'
		ORDER BY id ASC
		`,
		uid,
	)

	if err != nil {
		return nil, err
	}

	result := []model.Agent{}

	for rows.Next() {
		agent, err := scanAgent(
			rows,
		)

		if err != nil {
			_ = rows.Close()

			return nil, err
		}

		result = append(
			result,
			*agent,
		)
	}

	if err = rows.Err(); err != nil {
		_ = rows.Close()

		return nil, err
	}

	// 先释放第一个 ResultSet，
	// 再读取 Capability Profile。
	if err = rows.Close(); err != nil {
		return nil, err
	}

	if err = r.loadAgentCapabilityProfiles(
		ctx,
		uid,
		result,
	); err != nil {
		return nil, err
	}

	return result, nil
}

func (r *MySQL) DeleteAgent(
	ctx context.Context,
	uid int64,
	id int64,
) (bool, error) {
	res, err := r.db.ExecContext(
		ctx,
		`
		DELETE FROM agents
		WHERE id = ?
		  AND user_id = ?
		`,
		id,
		uid,
	)

	if err != nil {
		return false, err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected > 0, nil
}

// =========================================================
// Agent Experience Feedback
//
// Python Runtime
//       ↓
// AgentFeedback
//       ↓
// Go Control Plane
//       ↓
// MySQL
//
// 同时维护：
//
// 1. agent_runtime_metrics
// 2. agent_capability_profiles
// 3. agents aggregate metrics
// =========================================================

func (r *MySQL) RecordAgentFeedback(
	ctx context.Context,
	uid int64,
	requestID string,
	feedback []model.AgentFeedback,
) error {
	if len(
		feedback,
	) == 0 {
		return nil
	}

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

	const alpha = 0.2

	for _, item := range feedback {
		// =================================================
		// 1. Lock Agent + Tenant Ownership
		// =================================================

		var owner int64

		var globalQuality float64

		var globalLatency int64

		var globalCost float64

		var globalSuccess float64

		var globalFailure float64

		err = tx.QueryRowContext(
			ctx,
			`
			SELECT
				user_id,
				quality_score,
				avg_latency_ms,
				avg_cost,
				success_rate,
				failure_rate
			FROM agents
			WHERE id = ?
			LIMIT 1
			FOR UPDATE
			`,
			item.AgentID,
		).Scan(
			&owner,
			&globalQuality,
			&globalLatency,
			&globalCost,
			&globalSuccess,
			&globalFailure,
		)

		if errors.Is(
			err,
			sql.ErrNoRows,
		) {
			return ErrNotOwned
		}

		if err != nil {
			return err
		}

		if owner != uid {
			return ErrNotOwned
		}

		// =================================================
		// 2. Raw Runtime Metric
		// =================================================

		successInt := 0

		if item.Success {
			successInt = 1
		}

		var errorType any

		if item.ErrorType != "" {
			errorType = item.ErrorType
		}

		if _, err = tx.ExecContext(
			ctx,
			`
			INSERT INTO agent_runtime_metrics(
				agent_id,
				task_request_id,
				capability,
				success,
				latency_ms,
				cost,
				error_type
			)
			VALUES(
				?,
				?,
				?,
				?,
				?,
				?,
				?
			)
			`,
			item.AgentID,
			requestID,
			item.Capability,
			successInt,
			item.LatencyMS,
			item.Cost,
			errorType,
		); err != nil {
			return err
		}

		// =================================================
		// 3. Capability Profile Bootstrap
		// =================================================

		if _, err = tx.ExecContext(
			ctx,
			`
			INSERT IGNORE INTO agent_capability_profiles(
				agent_id,
				capability,
				quality_score,
				avg_latency_ms,
				avg_cost,
				success_rate,
				failure_rate,
				sample_count
			)
			VALUES(
				?,
				?,
				?,
				?,
				?,
				?,
				?,
				0
			)
			`,
			item.AgentID,
			item.Capability,
			globalQuality,
			globalLatency,
			globalCost,
			globalSuccess,
			globalFailure,
		); err != nil {
			return err
		}

		// =================================================
		// 4. Lock Capability Profile
		// =================================================

		var current model.AgentCapabilityProfile

		err = tx.QueryRowContext(
			ctx,
			`
			SELECT
				capability,
				quality_score,
				avg_latency_ms,
				avg_cost,
				success_rate,
				failure_rate,
				sample_count
			FROM agent_capability_profiles
			WHERE agent_id = ?
			  AND capability = ?
			LIMIT 1
			FOR UPDATE
			`,
			item.AgentID,
			item.Capability,
		).Scan(
			&current.Capability,
			&current.QualityScore,
			&current.AvgLatencyMS,
			&current.AvgCost,
			&current.SuccessRate,
			&current.FailureRate,
			&current.SampleCount,
		)

		if err != nil {
			return err
		}

		// =================================================
		// 5. Capability-level EWMA
		//
		// new =
		// old * 0.8
		// +
		// latest * 0.2
		// =================================================

		successFloat := 0.0

		if item.Success {
			successFloat = 1.0
		}

		nextSuccess :=
			(1.0-alpha)*
				current.SuccessRate +
				alpha*
					successFloat

		nextFailure :=
			1.0 -
				nextSuccess

		nextLatency := int64(
			math.Round(
				(1.0-alpha)*
					float64(
						current.AvgLatencyMS,
					) +
					alpha*
						float64(
							item.LatencyMS,
						),
			),
		)

		if nextLatency < 1 {
			nextLatency = 1
		}

		nextCost :=
			(1.0-alpha)*
				current.AvgCost +
				alpha*
					item.Cost

		nextQuality :=
			current.QualityScore

		// qualityScore=nil：
		//
		// 表示本次没有语义质量评价。
		//
		// 网络错误/Timeout 不应该再把
		// semantic quality 当成 0。
		if item.QualityScore != nil {
			nextQuality =
				(1.0-alpha)*
					current.QualityScore +
					alpha*
						(*item.QualityScore)
		}

		nextSampleCount :=
			current.SampleCount +
				1

		if _, err = tx.ExecContext(
			ctx,
			`
			UPDATE agent_capability_profiles
			SET
				quality_score = ?,
				avg_latency_ms = ?,
				avg_cost = ?,
				success_rate = ?,
				failure_rate = ?,
				sample_count = ?,
				updated_at = CURRENT_TIMESTAMP(6)
			WHERE agent_id = ?
			  AND capability = ?
			`,
			nextQuality,
			nextLatency,
			nextCost,
			nextSuccess,
			nextFailure,
			nextSampleCount,
			item.AgentID,
			item.Capability,
		); err != nil {
			return err
		}

		// =================================================
		// 6. Agent-level Aggregate
		//
		// 保留 Agent-level metrics：
		//
		// - backward compatibility
		// - capability profile 不存在时 fallback
		//
		// 这里不更新 global quality。
		//
		// 不同 capability 的质量不应该互相污染。
		// =================================================

		nextGlobalSuccess :=
			(1.0-alpha)*
				globalSuccess +
				alpha*
					successFloat

		nextGlobalFailure :=
			1.0 -
				nextGlobalSuccess

		nextGlobalLatency := int64(
			math.Round(
				(1.0-alpha)*
					float64(
						globalLatency,
					) +
					alpha*
						float64(
							item.LatencyMS,
						),
			),
		)

		if nextGlobalLatency < 1 {
			nextGlobalLatency = 1
		}

		nextGlobalCost :=
			(1.0-alpha)*
				globalCost +
				alpha*
					item.Cost

		if _, err = tx.ExecContext(
			ctx,
			`
			UPDATE agents
			SET
				avg_latency_ms = ?,
				avg_cost = ?,
				success_rate = ?,
				failure_rate = ?
			WHERE id = ?
			  AND user_id = ?
			`,
			nextGlobalLatency,
			nextGlobalCost,
			nextGlobalSuccess,
			nextGlobalFailure,
			item.AgentID,
			uid,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

// =========================================================
// Task
//
// v1.9.5B Long-lived Runtime Task
//
// 一个 Go Task ID 对应完整生命周期：
//
// RUNNING
//   ↓
// INPUT_REQUIRED / AUTH_REQUIRED
//   ↓
// Resume
//   ↓
// RUNNING
//   ↓
// COMPLETED
//
// Resume 不创建第二个 Task。
// =========================================================

const taskColumns = `
	id,
	user_id,
	conversation_id,
	request_id,
	task_text,
	scheduler,
	planner,
	execution_mode,
	synthesis_mode,
	model_selection_json,
	delivery_mode,
	constraints_json,
	status,
	result_text,
	selected_agents_json,
	trace_json,
	dag_json,
	latency_ms,
	estimated_cost,
	error_message,
	continuation_json,
	created_at,
	updated_at
`

// =========================================================
// Task Scanner
// =========================================================

func scanTask(
	s scanner,
) (*model.Task, error) {
	var task model.Task

	var conversationID sql.NullInt64

	var resultText sql.NullString

	var errorMessage sql.NullString

	var latency sql.NullInt64

	var cost sql.NullFloat64

	var constraintsJSON []byte

	var modelSelectionJSON []byte

	var selectedJSON []byte

	var traceJSON []byte

	var dagJSON []byte

	var continuationJSON []byte

	err := s.Scan(
		&task.ID,
		&task.UserID,
		&conversationID,
		&task.RequestID,
		&task.TaskText,
		&task.Scheduler,
		&task.Planner,
		&task.ExecutionMode,
		&task.SynthesisMode,
		&modelSelectionJSON,
		&task.DeliveryMode,
		&constraintsJSON,
		&task.Status,
		&resultText,
		&selectedJSON,
		&traceJSON,
		&dagJSON,
		&latency,
		&cost,
		&errorMessage,
		&continuationJSON,
		&task.CreatedAt,
		&task.UpdatedAt,
	)

	if errors.Is(
		err,
		sql.ErrNoRows,
	) {
		return nil, nil
	}

	if err != nil {
		return nil, err
	}

	// =====================================================
	// Nullable Scalar Fields
	// =====================================================

	if conversationID.Valid {
		value := conversationID.Int64

		task.ConversationID = &value
	}

	if resultText.Valid {
		value := resultText.String

		task.ResultText = &value
	}

	if latency.Valid {
		value := latency.Int64

		task.LatencyMS = &value
	}

	if cost.Valid {
		value := cost.Float64

		task.EstimatedCost = &value
	}

	if errorMessage.Valid {
		value := errorMessage.String

		task.ErrorMessage = &value
	}

	// =====================================================
	// Model Selection
	// =====================================================

	task.ModelSelection = model.ModelSelection{Mode: "auto"}
	if len(modelSelectionJSON) > 0 {
		_ = json.Unmarshal(modelSelectionJSON, &task.ModelSelection)
	}

	// =====================================================
	// Constraints
	// =====================================================

	if len(
		constraintsJSON,
	) > 0 {
		if err = json.Unmarshal(
			constraintsJSON,
			&task.Constraints,
		); err != nil {
			return nil, err
		}
	}

	// =====================================================
	// Selected Agents
	// =====================================================

	task.SelectedAgents =
		[]string{}

	if len(
		selectedJSON,
	) > 0 {
		_ = json.Unmarshal(
			selectedJSON,
			&task.SelectedAgents,
		)
	}

	// =====================================================
	// Trace
	// =====================================================

	task.Trace =
		[]map[string]any{}

	if len(
		traceJSON,
	) > 0 {
		_ = json.Unmarshal(
			traceJSON,
			&task.Trace,
		)
	}

	// =====================================================
	// DAG
	// =====================================================

	task.DAG =
		map[string]any{}

	if len(
		dagJSON,
	) > 0 {
		_ = json.Unmarshal(
			dagJSON,
			&task.DAG,
		)
	}

	// =====================================================
	// Runtime Continuation
	//
	// continuation_json 是服务端内部状态。
	//
	// model.Task 上 json:"-"，
	// 不直接暴露给普通 Task API。
	// =====================================================

	if len(
		continuationJSON,
	) > 0 {
		var continuation model.TaskContinuation

		if err = json.Unmarshal(
			continuationJSON,
			&continuation,
		); err != nil {
			return nil, err
		}

		task.Continuation =
			&continuation

		if strings.EqualFold(continuation.Protocol, "tool_approval") ||
			continuation.Kind == "tool_approval" {
			task.Approval = &model.TaskApproval{
				ApprovalID:           continuation.ApprovalID,
				ToolName:             continuation.ToolName,
				ToolProtocol:         continuation.ToolProtocol,
				RiskLevel:            continuation.RiskLevel,
				RequiresConfirmation: continuation.RequiresConfirmation,
				Summary:              continuation.Summary,
				ArgumentsPreview:     redactApprovalArguments(continuation.Arguments),
			}
		}
	}

	return &task, nil
}

func redactApprovalArguments(value map[string]any) map[string]any {
	if value == nil {
		return map[string]any{}
	}

	out := make(map[string]any, len(value))
	for key, item := range value {
		lower := strings.ToLower(key)
		if approvalKeyIsSensitive(lower) {
			out[key] = "[REDACTED]"
			continue
		}
		out[key] = redactApprovalValue(item)
	}
	return out
}

func approvalKeyIsSensitive(lower string) bool {
	for _, marker := range []string{
		"password", "token", "secret", "credential", "otp",
		"authorization", "api_key", "apikey",
	} {
		if strings.Contains(lower, marker) {
			return true
		}
	}
	return false
}

func approvalStringIsSensitive(value string) bool {
	lower := strings.ToLower(value)
	for _, marker := range []string{
		"password=", "password:", "token=", "token:",
		"credential=", "credential:", "otp=", "otp:",
		"authorization:", "bearer ", "api_key=", "api_key:",
		"apikey=", "apikey:",
	} {
		if strings.Contains(lower, marker) {
			return true
		}
	}
	return false
}

func redactApprovalValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		return redactApprovalArguments(typed)
	case []any:
		out := make([]any, 0, len(typed))
		for _, item := range typed {
			out = append(out, redactApprovalValue(item))
		}
		return out
	case string:
		if approvalStringIsSensitive(typed) {
			return "[REDACTED]"
		}
		if len(typed) > 160 {
			return typed[:160] + "…"
		}
		return typed
	default:
		return typed
	}
}

// =========================================================
// Create Task
//
// New Task:
//
// nil
//   ↓
// RUNNING
// =========================================================

func (r *MySQL) CreateTask(
	ctx context.Context,
	task model.Task,
	constraints model.TaskConstraints,
) (*model.Task, error) {
	constraintsJSON, err := json.Marshal(
		constraints,
	)

	if err != nil {
		return nil, err
	}

	modelSelectionJSON, err := json.Marshal(task.ModelSelection)
	if err != nil {
		return nil, err
	}

	res, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO tasks(
			user_id,
			conversation_id,
			request_id,
			task_text,
			scheduler,
			planner,
			execution_mode,
			synthesis_mode,
			model_selection_json,
			delivery_mode,
			constraints_json,
			status
		)
		VALUES(
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			?,
			'RUNNING'
		)
		`,
		task.UserID,
		task.ConversationID,
		task.RequestID,
		task.TaskText,
		task.Scheduler,
		task.Planner,
		task.ExecutionMode,
		task.SynthesisMode,
		string(modelSelectionJSON),
		"direct",
		string(
			constraintsJSON,
		),
	)

	if err != nil {
		return nil, err
	}

	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}

	return r.TaskByID(
		ctx,
		task.UserID,
		id,
	)
}

// =========================================================
// TaskByID
//
// ID + user_id 双条件：
//
// 既做读取，
// 也做租户 Ownership Boundary。
// =========================================================

func (r *MySQL) TaskByID(
	ctx context.Context,
	uid int64,
	id int64,
) (*model.Task, error) {
	return scanTask(
		r.db.QueryRowContext(
			ctx,
			`
			SELECT
			`+taskColumns+`
			FROM tasks
			WHERE id = ?
			  AND user_id = ?
			LIMIT 1
			`,
			id,
			uid,
		),
	)
}

// =========================================================
// Suspend Task
//
// RUNNING
//      ↓
// INPUT_REQUIRED
//
// or
//
// RUNNING
//      ↓
// AUTH_REQUIRED
//
// continuation 与等待状态必须一起写入。
// =========================================================

func (r *MySQL) SuspendTask(
	ctx context.Context,
	uid int64,
	id int64,
	status string,
	result string,
	continuation *model.TaskContinuation,
	selected []string,
	trace []map[string]any,
	dag map[string]any,
	latency int64,
	cost float64,
) error {
	if continuation == nil {
		return errors.New(
			"continuation is required",
		)
	}

	if status != "INPUT_REQUIRED" &&
		status != "AUTH_REQUIRED" {
		return ErrInvalidTaskState
	}

	continuationJSON, err := json.Marshal(
		continuation,
	)

	if err != nil {
		return err
	}

	selectedJSON, err := json.Marshal(
		selected,
	)

	if err != nil {
		return err
	}

	traceJSON, err := json.Marshal(
		trace,
	)

	if err != nil {
		return err
	}

	dagJSON, err := json.Marshal(
		dag,
	)

	if err != nil {
		return err
	}

	res, err := r.db.ExecContext(
		ctx,
		`
		UPDATE tasks
		SET
			status = ?,
			result_text = ?,
			selected_agents_json = ?,
			trace_json = ?,
			dag_json = ?,
			latency_ms = ?,
			estimated_cost = ?,
			error_message = NULL,
			continuation_json = ?
		WHERE id = ?
		  AND user_id = ?
		  AND status = 'RUNNING'
		`,
		status,
		result,
		string(
			selectedJSON,
		),
		string(
			traceJSON,
		),
		string(
			dagJSON,
		),
		latency,
		cost,
		string(
			continuationJSON,
		),
		id,
		uid,
	)

	if err != nil {
		return err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return err
	}

	if affected != 1 {
		return ErrInvalidTaskState
	}

	return nil
}

// =========================================================
// Begin Task Resume
//
// INPUT_REQUIRED
//        │
//        ├── Resume Request A
//        │
//        └── Resume Request B
//
// DB CAS:
//
// waiting
//   ↓
// RUNNING
//
// 两个并发 Resume 中只有一个 affectedRows=1。
// =========================================================

func (r *MySQL) BeginTaskResume(
	ctx context.Context,
	uid int64,
	id int64,
) (bool, error) {
	res, err := r.db.ExecContext(
		ctx,
		`
		UPDATE tasks
		SET
			status = 'RUNNING',
			error_message = NULL
		WHERE id = ?
		  AND user_id = ?
		  AND status IN (
				'INPUT_REQUIRED',
				'AUTH_REQUIRED'
		  )
		  AND continuation_json IS NOT NULL
		`,
		id,
		uid,
	)

	if err != nil {
		return false, err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}

	return affected == 1, nil
}

// =========================================================
// Complete Task
//
// RUNNING
//      ↓
// COMPLETED
//
// 完成以后 continuation 失效并清理。
// =========================================================

func (r *MySQL) CompleteTask(
	ctx context.Context,
	uid int64,
	id int64,
	result string,
	selected []string,
	trace []map[string]any,
	dag map[string]any,
	latency int64,
	cost float64,
) error {
	selectedJSON, err := json.Marshal(
		selected,
	)

	if err != nil {
		return err
	}

	traceJSON, err := json.Marshal(
		trace,
	)

	if err != nil {
		return err
	}

	dagJSON, err := json.Marshal(
		dag,
	)

	if err != nil {
		return err
	}

	res, err := r.db.ExecContext(
		ctx,
		`
		UPDATE tasks
		SET
			status = 'COMPLETED',
			result_text = ?,
			selected_agents_json = ?,
			trace_json = ?,
			dag_json = ?,
			latency_ms = ?,
			estimated_cost = ?,
			error_message = NULL,
			continuation_json = NULL
		WHERE id = ?
		  AND user_id = ?
		  AND status = 'RUNNING'
		`,
		result,
		string(
			selectedJSON,
		),
		string(
			traceJSON,
		),
		string(
			dagJSON,
		),
		latency,
		cost,
		id,
		uid,
	)

	if err != nil {
		return err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return err
	}

	if affected != 1 {
		return ErrInvalidTaskState
	}

	return nil
}

// =========================================================
// Fail Task
//
// RUNNING
//      ↓
// ERROR
//
// Failure 后 continuation 也必须失效。
// =========================================================

func (r *MySQL) FailTask(
	ctx context.Context,
	uid int64,
	id int64,
	message string,
	latency int64,
) error {
	res, err := r.db.ExecContext(
		ctx,
		`
		UPDATE tasks
		SET
			status = 'ERROR',
			error_message = ?,
			latency_ms = ?,
			continuation_json = NULL
		WHERE id = ?
		  AND user_id = ?
		  AND status = 'RUNNING'
		`,
		message,
		latency,
		id,
		uid,
	)

	if err != nil {
		return err
	}

	affected, err := res.RowsAffected()
	if err != nil {
		return err
	}

	if affected != 1 {
		return ErrInvalidTaskState
	}

	return nil
}

// =========================================================
// List Tasks
// =========================================================

func (r *MySQL) ListTasks(
	ctx context.Context,
	uid int64,
	limit int,
) ([]model.Task, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
		`+taskColumns+`
		FROM tasks
		WHERE user_id = ?
		ORDER BY id DESC
		LIMIT ?
		`,
		uid,
		limit,
	)

	if err != nil {
		return nil, err
	}

	defer rows.Close()

	result :=
		[]model.Task{}

	for rows.Next() {
		task, err := scanTask(
			rows,
		)

		if err != nil {
			return nil, err
		}

		result = append(
			result,
			*task,
		)
	}

	return result, rows.Err()
}

// =========================================================
// Debug
// =========================================================

func (r *MySQL) DebugCounts(
	ctx context.Context,
) (string, error) {
	var users int

	var agents int

	var tasks int

	queries := map[string]*int{
		`
		SELECT COUNT(*)
		FROM users
		`: &users,

		`
		SELECT COUNT(*)
		FROM agents
		`: &agents,

		`
		SELECT COUNT(*)
		FROM tasks
		`: &tasks,
	}

	for query, target := range queries {
		if err := r.db.QueryRowContext(
			ctx,
			query,
		).Scan(
			target,
		); err != nil {
			return "", err
		}
	}

	return fmt.Sprintf(
		"users=%d agents=%d tasks=%d",
		users,
		agents,
		tasks,
	), nil
}

// =========================================================
// Conversation Memory Capsules
// =========================================================

func scanConversationMemoryCapsule(s scanner) (*model.ConversationMemoryCapsule, error) {
	var item model.ConversationMemoryCapsule
	var factsJSON []byte
	var decisionsJSON []byte
	var openTasksJSON []byte
	var entitiesJSON []byte
	var keywordsJSON []byte
	var estimatedCost sql.NullFloat64

	if err := s.Scan(
		&item.ID,
		&item.UserID,
		&item.ConversationID,
		&item.StartMessageID,
		&item.EndMessageID,
		&item.Summary,
		&factsJSON,
		&decisionsJSON,
		&openTasksJSON,
		&entitiesJSON,
		&keywordsJSON,
		&item.Importance,
		&item.SourceHash,
		&item.CompactionModel,
		&item.InputTokens,
		&item.OutputTokens,
		&estimatedCost,
		&item.CreatedAt,
		&item.UpdatedAt,
	); err != nil {
		return nil, err
	}

	_ = json.Unmarshal(factsJSON, &item.Facts)
	_ = json.Unmarshal(decisionsJSON, &item.Decisions)
	_ = json.Unmarshal(openTasksJSON, &item.OpenTasks)
	_ = json.Unmarshal(entitiesJSON, &item.Entities)
	_ = json.Unmarshal(keywordsJSON, &item.Keywords)
	if item.Facts == nil {
		item.Facts = []string{}
	}
	if item.Decisions == nil {
		item.Decisions = []string{}
	}
	if item.OpenTasks == nil {
		item.OpenTasks = []string{}
	}
	if item.Entities == nil {
		item.Entities = []string{}
	}
	if item.Keywords == nil {
		item.Keywords = []string{}
	}
	if estimatedCost.Valid {
		value := estimatedCost.Float64
		item.EstimatedCost = &value
	}
	return &item, nil
}

func (r *MySQL) ensureConversationOwned(ctx context.Context, uid, conversationID int64) error {
	var id int64
	if err := r.db.QueryRowContext(
		ctx,
		`SELECT id FROM conversations WHERE id = ? AND user_id = ? LIMIT 1`,
		conversationID,
		uid,
	).Scan(&id); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return ErrNotOwned
		}
		return err
	}
	return nil
}

func (r *MySQL) ListConversationMemoryCapsules(
	ctx context.Context,
	uid int64,
	conversationID int64,
	limit int,
) ([]model.ConversationMemoryCapsule, error) {
	if err := r.ensureConversationOwned(ctx, uid, conversationID); err != nil {
		return nil, err
	}
	if limit <= 0 {
		return []model.ConversationMemoryCapsule{}, nil
	}

	rows, err := r.db.QueryContext(
		ctx,
		`SELECT
			id,user_id,conversation_id,start_message_id,end_message_id,summary,
			facts_json,decisions_json,open_tasks_json,entities_json,keywords_json,
			importance,source_hash,compaction_model,input_tokens,output_tokens,estimated_cost,created_at,updated_at
		 FROM conversation_memory_capsules
		 WHERE user_id = ? AND conversation_id = ?
		 ORDER BY end_message_id DESC
		 LIMIT ?`,
		uid,
		conversationID,
		limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]model.ConversationMemoryCapsule, 0, limit)
	for rows.Next() {
		item, scanErr := scanConversationMemoryCapsule(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		items = append(items, *item)
	}
	return items, rows.Err()
}

func (r *MySQL) UpsertConversationMemoryCapsule(
	ctx context.Context,
	uid int64,
	conversationID int64,
	input model.ConversationMemoryCapsuleWrite,
) (*model.ConversationMemoryCapsule, error) {
	if err := r.ensureConversationOwned(ctx, uid, conversationID); err != nil {
		return nil, err
	}

	factsJSON, _ := json.Marshal(input.Facts)
	decisionsJSON, _ := json.Marshal(input.Decisions)
	openTasksJSON, _ := json.Marshal(input.OpenTasks)
	entitiesJSON, _ := json.Marshal(input.Entities)
	keywordsJSON, _ := json.Marshal(input.Keywords)

	_, err := r.db.ExecContext(
		ctx,
		`INSERT INTO conversation_memory_capsules(
			user_id,conversation_id,start_message_id,end_message_id,summary,
			facts_json,decisions_json,open_tasks_json,entities_json,keywords_json,
			importance,source_hash,compaction_model,input_tokens,output_tokens,estimated_cost
		 ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
		 ON DUPLICATE KEY UPDATE
			summary=VALUES(summary),
			facts_json=VALUES(facts_json),
			decisions_json=VALUES(decisions_json),
			open_tasks_json=VALUES(open_tasks_json),
			entities_json=VALUES(entities_json),
			keywords_json=VALUES(keywords_json),
			importance=VALUES(importance),
			source_hash=VALUES(source_hash),
			compaction_model=VALUES(compaction_model),
			input_tokens=VALUES(input_tokens),
			output_tokens=VALUES(output_tokens),
			estimated_cost=VALUES(estimated_cost),
			updated_at=CURRENT_TIMESTAMP(6)`,
		uid,
		conversationID,
		input.StartMessageID,
		input.EndMessageID,
		input.Summary,
		factsJSON,
		decisionsJSON,
		openTasksJSON,
		entitiesJSON,
		keywordsJSON,
		input.Importance,
		input.SourceHash,
		input.CompactionModel,
		input.InputTokens,
		input.OutputTokens,
		input.EstimatedCost,
	)
	if err != nil {
		return nil, err
	}

	row := r.db.QueryRowContext(
		ctx,
		`SELECT
			id,user_id,conversation_id,start_message_id,end_message_id,summary,
			facts_json,decisions_json,open_tasks_json,entities_json,keywords_json,
			importance,source_hash,compaction_model,input_tokens,output_tokens,estimated_cost,created_at,updated_at
		 FROM conversation_memory_capsules
		 WHERE user_id = ? AND conversation_id = ?
		   AND start_message_id = ? AND end_message_id = ?
		 LIMIT 1`,
		uid,
		conversationID,
		input.StartMessageID,
		input.EndMessageID,
	)
	return scanConversationMemoryCapsule(row)
}

func (r *MySQL) ConversationCompactionWindow(
	ctx context.Context,
	uid int64,
	conversationID int64,
	afterID int64,
	minMessages int,
	maxMessages int,
	reserveRecent int,
) ([]model.Message, error) {
	if err := r.ensureConversationOwned(ctx, uid, conversationID); err != nil {
		return nil, err
	}

	fetchLimit := maxMessages + reserveRecent
	rows, err := r.db.QueryContext(
		ctx,
		`SELECT id, conversation_id, role, content, status, request_id, metadata_json, created_at
		 FROM messages
		 WHERE conversation_id = ?
		   AND id > ?
		   AND role IN ('user','assistant')
		   AND content <> ''
		 ORDER BY id ASC
		 LIMIT ?`,
		conversationID,
		afterID,
		fetchLimit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]model.Message, 0, fetchLimit)
	for rows.Next() {
		item, scanErr := scanMessage(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		items = append(items, *item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	if len(items) < minMessages+reserveRecent {
		return []model.Message{}, nil
	}
	eligible := len(items) - reserveRecent
	if eligible > maxMessages {
		eligible = maxMessages
	}
	if eligible < minMessages {
		return []model.Message{}, nil
	}
	return items[:eligible], nil
}
