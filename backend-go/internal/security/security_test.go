package security

import "testing"

func TestPassword(t *testing.T) {
	h, e := HashPassword("Test123456")
	if e != nil {
		t.Fatal(e)
	}
	if !ComparePassword(h, "Test123456") {
		t.Fatal("should match")
	}
	if ComparePassword(h, "wrong") {
		t.Fatal("should not match")
	}
}
func TestRefresh(t *testing.T) {
	raw, h, e := GenerateRefreshToken()
	if e != nil {
		t.Fatal(e)
	}
	if HashRefreshToken(raw) != h {
		t.Fatal("hash mismatch")
	}
}
