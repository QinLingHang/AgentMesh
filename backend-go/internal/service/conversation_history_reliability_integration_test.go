package service

import (
	"context"
	"fmt"
	"testing"

	"example.com/agentmesh-control-plane/internal/repository"
)

func TestConversationReliabilityDurableConversationHistoryPagesThroughEveryMessage(t *testing.T) {
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
		"conversation-reliability-history@example.test", "fixture", "Conversation Reliability History",
	)
	conversationID := insert(
		"INSERT INTO conversations(user_id,title) VALUES(?,?)",
		uid, "Conversation Reliability durable history",
	)

	const total = 125
	for index := 1; index <= total; index++ {
		role := "user"
		if index%2 == 0 {
			role = "assistant"
		}
		insert(
			"INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,?,?,?,?,?)",
			conversationID, role, fmt.Sprintf("conversation-reliability-message-%03d", index), "COMPLETED",
			fmt.Sprintf("conversation-reliability-request-%03d", (index+1)/2), "{}",
		)
	}

	beforeID := int64(0)
	collected := make([]string, 0, total)
	seen := map[int64]bool{}
	pages := 0

	for {
		items, hasMore, err := repo.ListMessagesBefore(ctx, uid, conversationID, beforeID, 40)
		if err != nil {
			t.Fatal(err)
		}
		pages++
		if len(items) == 0 {
			t.Fatal("unexpected empty page")
		}
		for _, item := range items {
			if seen[item.ID] {
				t.Fatalf("duplicate message id %d", item.ID)
			}
			seen[item.ID] = true
			collected = append(collected, item.Content)
		}
		if !hasMore {
			break
		}
		beforeID = items[0].ID
	}

	if pages != 4 {
		t.Fatalf("expected 4 pages, got %d", pages)
	}
	if len(collected) != total {
		t.Fatalf("expected %d durable messages, got %d", total, len(collected))
	}

	// Pages are fetched newest-first at the page level. Verify every expected
	// row remains reachable rather than relying on one unbounded response.
	expected := map[string]bool{}
	for index := 1; index <= total; index++ {
		expected[fmt.Sprintf("conversation-reliability-message-%03d", index)] = true
	}
	for _, content := range collected {
		delete(expected, content)
	}
	if len(expected) != 0 {
		t.Fatalf("missing durable messages: %v", expected)
	}
}
