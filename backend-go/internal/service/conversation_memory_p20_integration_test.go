package service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

func TestP20ConversationMemoryCapsulesAreDurableAndKeepRecentRawMessages(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)

	insert := func(query string, args ...any) int64 {
		t.Helper()
		result, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := result.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}

	uid := insert(
		"INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		"p20-capsule@example.test", "fixture", "P20 Capsule",
	)
	conversationID := insert(
		"INSERT INTO conversations(user_id,title) VALUES(?,?)",
		uid, "P20 memory capsule",
	)

	messageIDs := make([]int64, 0, 24)
	for index := 1; index <= 24; index++ {
		role := "user"
		if index%2 == 0 {
			role = "assistant"
		}
		messageIDs = append(messageIDs, insert(
			"INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,?,?,?,?,?)",
			conversationID, role, fmt.Sprintf("capsule-message-%02d", index), "COMPLETED",
			fmt.Sprintf("capsule-request-%02d", (index+1)/2), "{}",
		))
	}

	window, err := repo.ConversationCompactionWindow(ctx, uid, conversationID, 0, 12, 18, 8)
	if err != nil {
		t.Fatal(err)
	}
	if len(window) != 16 {
		t.Fatalf("expected 16 compactable messages while reserving newest 8, got %d", len(window))
	}
	if window[0].ID != messageIDs[0] || window[len(window)-1].ID != messageIDs[15] {
		t.Fatalf("unexpected compaction range: %d..%d", window[0].ID, window[len(window)-1].ID)
	}

	capsule, err := repo.UpsertConversationMemoryCapsule(
		ctx,
		uid,
		conversationID,
		model.ConversationMemoryCapsuleWrite{
			StartMessageID:  window[0].ID,
			EndMessageID:    window[len(window)-1].ID,
			Summary:         "Desktop 默认 Embedded；继续 P20 验收。",
			Facts:           []string{"完整聊天历史仍由 MySQL 保存"},
			Decisions:       []string{"Redis 只保留短期工作窗口"},
			OpenTasks:       []string{"继续人工验收"},
			Entities:        []string{"AgentMesh", "Redis"},
			Keywords:        []string{"memory", "conversation"},
			Importance:      0.91,
			SourceHash:      strings.Repeat("a", 64),
			CompactionModel: "cheap-memory-model",
			InputTokens:     123,
			OutputTokens:    45,
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	if capsule.StartMessageID != messageIDs[0] || capsule.EndMessageID != messageIDs[15] {
		t.Fatalf("persisted capsule range mismatch: %+v", capsule)
	}

	capsules, err := repo.ListConversationMemoryCapsules(ctx, uid, conversationID, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(capsules) != 1 || capsules[0].Summary == "" || capsules[0].Importance != 0.91 ||
		capsules[0].CompactionModel != "cheap-memory-model" || capsules[0].InputTokens != 123 ||
		capsules[0].OutputTokens != 45 {
		t.Fatalf("unexpected persisted capsule: %+v", capsules)
	}

	nextWindow, err := repo.ConversationCompactionWindow(
		ctx,
		uid,
		conversationID,
		capsule.EndMessageID,
		12,
		18,
		8,
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(nextWindow) != 0 {
		t.Fatalf("newest 8 raw messages must remain uncompressed, got %d", len(nextWindow))
	}

	allMessages, err := repo.ListMessages(ctx, uid, conversationID, 100)
	if err != nil {
		t.Fatal(err)
	}
	if len(allMessages) != 24 {
		t.Fatalf("capsule creation must never delete raw history: got %d messages", len(allMessages))
	}
}

func TestP20ConversationMemoryOwnershipIdempotencyAndCascade(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	conversations := NewConversationService(repo, repo)

	insert := func(query string, args ...any) int64 {
		t.Helper()
		result, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := result.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}

	uidA := insert(
		"INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		"p20-memory-a@example.test", "fixture", "P20 Memory A",
	)
	uidB := insert(
		"INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		"p20-memory-b@example.test", "fixture", "P20 Memory B",
	)
	conversationID := insert(
		"INSERT INTO conversations(user_id,title) VALUES(?,?)",
		uidA, "P20 memory ownership",
	)
	startMessageID := insert(
		"INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,?,?,?,?,?)",
		conversationID, "user", "remember desktop embedded mode", "COMPLETED", "p20-memory-own-1", "{}",
	)
	endMessageID := insert(
		"INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,?,?,?,?,?)",
		conversationID, "assistant", "desktop embedded mode is the current decision", "COMPLETED", "p20-memory-own-1", "{}",
	)

	write := model.ConversationMemoryCapsuleWrite{
		StartMessageID: startMessageID,
		EndMessageID:   endMessageID,
		Summary:        "Desktop defaults to Embedded mode.",
		Facts:          []string{"raw history remains durable in MySQL"},
		Importance:     0.9,
		SourceHash:     strings.Repeat("b", 64),
	}
	first, err := conversations.UpsertMemoryCapsule(ctx, uidA, conversationID, write)
	if err != nil {
		t.Fatal(err)
	}

	write.Summary = "Desktop defaults to Embedded mode; duplicate range updates in place."
	second, err := conversations.UpsertMemoryCapsule(ctx, uidA, conversationID, write)
	if err != nil {
		t.Fatal(err)
	}
	if first.ID != second.ID {
		t.Fatalf("same message range must be idempotent: first=%d second=%d", first.ID, second.ID)
	}

	items, err := conversations.MemoryCapsules(ctx, uidA, conversationID, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Summary != write.Summary {
		t.Fatalf("expected one updated capsule, got %+v", items)
	}

	if _, err := conversations.MemoryCapsules(ctx, uidB, conversationID, 10); !errors.Is(err, ErrNotFound) {
		t.Fatalf("cross-user capsule lookup must fail closed with ErrNotFound, got %v", err)
	}

	if err := conversations.Delete(ctx, uidA, conversationID); err != nil {
		t.Fatal(err)
	}
	var capsuleCount int
	if err := database.QueryRow(
		"SELECT COUNT(*) FROM conversation_memory_capsules WHERE conversation_id=?",
		conversationID,
	).Scan(&capsuleCount); err != nil {
		t.Fatal(err)
	}
	if capsuleCount != 0 {
		t.Fatalf("conversation delete must cascade memory capsules, got %d", capsuleCount)
	}
}
