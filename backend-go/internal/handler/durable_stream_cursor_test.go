package handler

import "testing"

func TestDurableSSECursorBackwardCompatibleAndComposite(t *testing.T) {
	legacy, err := parseDurableSSECursor("42")
	if err != nil || legacy.State != 42 || legacy.Delta != "0-0" || legacy.Fence != 0 {
		t.Fatalf("legacy cursor mismatch: %+v err=%v", legacy, err)
	}
	composite, err := parseDurableSSECursor("s=42;d=3-19;f=3")
	if err != nil || composite.State != 42 || composite.Delta != "3-19" || composite.Fence != 3 {
		t.Fatalf("composite cursor mismatch: %+v err=%v", composite, err)
	}
	if got := formatDurableSSECursor(composite); got != "s=42;d=3-19;f=3" {
		t.Fatalf("round trip mismatch: %s", got)
	}
}

func TestDurableSSECursorRejectsMalformedValues(t *testing.T) {
	for _, raw := range []string{"-1", "s=1;d=bad;f=1", "s=1;d=1-1", "s=1;d=1-1;f=-1", "s=1;d=1-1;f=1;x=2"} {
		if _, err := parseDurableSSECursor(raw); err == nil {
			t.Fatalf("expected invalid cursor: %q", raw)
		}
	}
}
