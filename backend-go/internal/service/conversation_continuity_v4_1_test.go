package service

import (
	"fmt"
	"strings"
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
)

func TestContinuationTurnsDoNotUseContextBlindInteractiveFastPath(t *testing.T) {
	turns := []string{
		"继续",
		"继续吧",
		"可以",
		"可以。",
		"好的",
		"好的，继续",
		"然后呢",
		"下一步",
		"go on",
		"yes",
	}

	for _, turn := range turns {
		if ShouldUseInteractiveFastPath(turn, nil) {
			t.Fatalf("continuation turn %q must preserve full conversation/runtime context", turn)
		}
	}
}

func TestBoundedInteractiveHistoryKeepsNewestTurnsInChronologicalOrder(t *testing.T) {
	messages := make([]model.Message, 0, 20)
	for i := 1; i <= 20; i++ {
		role := "user"
		if i%2 == 0 {
			role = "assistant"
		}
		messages = append(messages, model.Message{
			ID:      int64(i),
			Role:    role,
			Content: fmt.Sprintf("message-%02d", i),
		})
	}

	history := boundedInteractiveHistory(messages)
	if len(history) != 8 {
		t.Fatalf("expected 8 recent messages, got %d", len(history))
	}
	if history[0].Content != "message-13" || history[7].Content != "message-20" {
		t.Fatalf("expected newest chronological window 13..20, got first=%q last=%q", history[0].Content, history[7].Content)
	}
}

func TestContinuationClassifierDoesNotStealSubstantiveShortQuestions(t *testing.T) {
	if !ShouldUseInteractiveFastPath("可以介绍一下 Java 吗？", nil) {
		t.Fatal("substantive short question must remain ordinary interactive chat")
	}
}
func TestBareOptionRepliesAreContinuationTurns(t *testing.T) {
	for _, turn := range []string{"1", "2", "3", "A", "b"} {
		if ShouldUseInteractiveFastPath(turn, nil) {
			t.Fatalf("bare option reply %q must preserve full conversation context", turn)
		}
	}
}

func TestBoundedInteractiveHistoryPreservesLongAssistantTail(t *testing.T) {
	long := "最大子数组和讲解："
	for i := 0; i < 400; i++ {
		long += "中间推导"
	}
	long += "\n选项：1. 用 Python 跑一遍；2. 画状态转移；3. 换数组练习。"

	history := boundedInteractiveHistory([]model.Message{
		{ID: 1, Role: "user", Content: "最大子数组和没思路"},
		{ID: 2, Role: "assistant", Content: long},
	})
	if len(history) != 2 {
		t.Fatalf("history len=%d", len(history))
	}
	if !strings.Contains(history[1].Content, "1. 用 Python 跑一遍") ||
		!strings.Contains(history[1].Content, "3. 换数组练习") {
		t.Fatalf("assistant tail was truncated away: %q", history[1].Content)
	}
}
