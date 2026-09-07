package repository

import (
	"fmt"
	"testing"
)

func TestRedactApprovalArgumentsNestedSensitiveValues(t *testing.T) {
	preview := redactApprovalArguments(map[string]any{
		"order_id": "ORDER-1",
		"password": "secret-value",
		"nested": map[string]any{
			"token": "abc",
			"note":  "credential: hidden",
		},
		"items": []any{
			map[string]any{"otp": "654321"},
			"bearer super-secret",
		},
	})

	if preview["password"] != "[REDACTED]" {
		t.Fatalf("password preview=%v", preview["password"])
	}
	if preview["nested"].(map[string]any)["token"] != "[REDACTED]" {
		t.Fatal("nested token was not redacted")
	}
	items := preview["items"].([]any)
	if items[0].(map[string]any)["otp"] != "[REDACTED]" || items[1] != "[REDACTED]" {
		t.Fatalf("nested list leaked sensitive data: %s", fmt.Sprint(items))
	}
	text := fmt.Sprint(preview)
	for _, secret := range []string{"secret-value", "654321", "super-secret"} {
		if containsText(text, secret) {
			t.Fatalf("preview leaked %s", secret)
		}
	}
}

func containsText(haystack, needle string) bool {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}
