package service

import "testing"

func TestKnowledgeRuntimeClientRequestIDValidation(t *testing.T) {
	for _, tc := range []struct {
		id    string
		valid bool
	}{
		{"", true}, {"3c8b00bf-5548-4c89-a4e8-3ef81282acc9", true},
		{"req_12345678", true}, {"short", false},
		{"bad key spaces", false}, {"../../../../../etc", false},
	} {
		if got := validClientRequestID(tc.id); got != tc.valid {
			t.Errorf("validClientRequestID(%q) = %v, want %v", tc.id, got, tc.valid)
		}
	}
}
