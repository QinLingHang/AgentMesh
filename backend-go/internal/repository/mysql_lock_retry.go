package repository

import (
	"context"
	"errors"
	"math/rand"
	"time"

	mysqlDriver "github.com/go-sql-driver/mysql"
)

const mysqlLockRetryAttempts = 3

func isRetryableMySQLLockError(err error) bool {
	var mysqlErr *mysqlDriver.MySQLError
	if !errors.As(err, &mysqlErr) {
		return false
	}
	return mysqlErr.Number == 1205 || mysqlErr.Number == 1213 || string(mysqlErr.SQLState[:]) == "40001"
}

func waitForMySQLLockRetry(ctx context.Context, attempt int) error {
	base := time.Duration(attempt+1) * 20 * time.Millisecond
	jitter := time.Duration(rand.Int63n(int64(10 * time.Millisecond)))
	timer := time.NewTimer(base + jitter)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func withMySQLLockRetry(ctx context.Context, attempts int, operation func() error) error {
	if attempts < 1 {
		attempts = 1
	}
	var lastErr error
	for attempt := 0; attempt < attempts; attempt++ {
		lastErr = operation()
		if lastErr == nil || !isRetryableMySQLLockError(lastErr) || attempt == attempts-1 {
			return lastErr
		}
		if err := waitForMySQLLockRetry(ctx, attempt); err != nil {
			return err
		}
	}
	return lastErr
}
