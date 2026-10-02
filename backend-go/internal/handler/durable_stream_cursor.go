package handler

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
)

type durableSSECursor struct {
	State int64
	Delta string
	Fence int64
}

func parseDurableSSECursor(raw string) (durableSSECursor, error) {
	cursor := durableSSECursor{Delta: "0-0"}
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return cursor, nil
	}
	// Backwards compatibility with the state-only SSE cursor used before P25.
	if !strings.Contains(raw, "=") {
		state, err := strconv.ParseInt(raw, 10, 64)
		if err != nil || state < 0 {
			return durableSSECursor{}, errors.New("invalid durable SSE cursor")
		}
		cursor.State = state
		return cursor, nil
	}
	seen := map[string]bool{}
	for _, part := range strings.Split(raw, ";") {
		pair := strings.SplitN(strings.TrimSpace(part), "=", 2)
		if len(pair) != 2 || seen[pair[0]] {
			return durableSSECursor{}, errors.New("invalid durable SSE cursor")
		}
		seen[pair[0]] = true
		switch pair[0] {
		case "s":
			value, err := strconv.ParseInt(pair[1], 10, 64)
			if err != nil || value < 0 {
				return durableSSECursor{}, errors.New("invalid durable SSE state cursor")
			}
			cursor.State = value
		case "d":
			if !validRedisStreamID(pair[1]) {
				return durableSSECursor{}, errors.New("invalid durable SSE delta cursor")
			}
			cursor.Delta = pair[1]
		case "f":
			value, err := strconv.ParseInt(pair[1], 10, 64)
			if err != nil || value < 0 {
				return durableSSECursor{}, errors.New("invalid durable SSE fence cursor")
			}
			cursor.Fence = value
		default:
			return durableSSECursor{}, errors.New("invalid durable SSE cursor field")
		}
	}
	if !seen["s"] || !seen["d"] || !seen["f"] {
		return durableSSECursor{}, errors.New("incomplete durable SSE cursor")
	}
	return cursor, nil
}

func formatDurableSSECursor(cursor durableSSECursor) string {
	delta := cursor.Delta
	if delta == "" {
		delta = "0-0"
	}
	return fmt.Sprintf("s=%d;d=%s;f=%d", cursor.State, delta, cursor.Fence)
}

func validRedisStreamID(value string) bool {
	parts := strings.Split(value, "-")
	if len(parts) != 2 {
		return false
	}
	major, errMajor := strconv.ParseInt(parts[0], 10, 64)
	minor, errMinor := strconv.ParseInt(parts[1], 10, 64)
	return errMajor == nil && errMinor == nil && major >= 0 && minor >= 0
}
