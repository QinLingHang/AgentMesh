package service

import (
	"context"
	"fmt"
	"testing"

	"example.com/agentmesh-control-plane/internal/repository"
)

func TestV41ListMessagesReturnsNewestWindowInChronologicalOrder(t *testing.T) {
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
		"v41-history@example.test",
		"fixture",
		"V4.1 History",
	)
	conversationID := insert(
		"INSERT INTO conversations(user_id,title) VALUES(?,?)",
		uid,
		"V4.1 newest history",
	)

	for index := 1; index <= 20; index++ {
		role := "user"
		if index%2 == 0 {
			role = "assistant"
		}
		insert(
			"INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,?,?,?,?,?)",
			conversationID,
			role,
			fmt.Sprintf("message-%02d", index),
			"COMPLETED",
			fmt.Sprintf("v41-history-%02d", index),
			"{}",
		)
	}

	messages, err := repo.ListMessages(ctx, uid, conversationID, 12)
	if err != nil {
		t.Fatal(err)
	}
	if len(messages) != 12 {
		t.Fatalf("expected 12 newest messages, got %d", len(messages))
	}
	if messages[0].Content != "message-09" || messages[11].Content != "message-20" {
		t.Fatalf(
			"expected chronological newest window message-09..message-20, got %q..%q",
			messages[0].Content,
			messages[11].Content,
		)
	}
}
