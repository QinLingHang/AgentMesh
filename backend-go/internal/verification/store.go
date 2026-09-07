package verification

import (
	"context"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"
)

var ErrStoreKeyNotFound = errors.New(
	"verification store key not found",
)

// Store contains only the Redis semantics required by verification codes.
//
// Service does not depend on *redis.Client directly.
// This keeps business rules testable.
type Store interface {
	SetCode(
		ctx context.Context,
		key string,
		value string,
		ttl time.Duration,
	) error

	GetCode(
		ctx context.Context,
		key string,
	) (string, error)

	SetRecord(
		ctx context.Context,
		key string,
		value string,
		ttl time.Duration,
	) error

	GetRecord(
		ctx context.Context,
		key string,
	) (string, error)

	Delete(
		ctx context.Context,
		keys ...string,
	) error

	AcquireCooldown(
		ctx context.Context,
		key string,
		ttl time.Duration,
	) (bool, error)

	IncrementWindowCounter(
		ctx context.Context,
		key string,
		window time.Duration,
	) (int64, error)

	IncrementAttemptCounter(
		ctx context.Context,
		key string,
		ttl time.Duration,
	) (int64, error)
}

type RedisStore struct {
	client *redis.Client
}

func NewRedisStore(
	client *redis.Client,
) *RedisStore {
	return &RedisStore{
		client: client,
	}
}

func (s *RedisStore) SetCode(
	ctx context.Context,
	key string,
	value string,
	ttl time.Duration,
) error {
	return s.client.Set(
		ctx,
		key,
		value,
		ttl,
	).Err()
}

func (s *RedisStore) GetCode(
	ctx context.Context,
	key string,
) (string, error) {
	return s.get(
		ctx,
		key,
	)
}

func (s *RedisStore) SetRecord(
	ctx context.Context,
	key string,
	value string,
	ttl time.Duration,
) error {
	return s.client.Set(
		ctx,
		key,
		value,
		ttl,
	).Err()
}

func (s *RedisStore) GetRecord(
	ctx context.Context,
	key string,
) (string, error) {
	return s.get(
		ctx,
		key,
	)
}

func (s *RedisStore) get(
	ctx context.Context,
	key string,
) (string, error) {
	value, err := s.client.Get(
		ctx,
		key,
	).Result()

	if errors.Is(
		err,
		redis.Nil,
	) {
		return "",
			ErrStoreKeyNotFound
	}

	return value,
		err
}

func (s *RedisStore) Delete(
	ctx context.Context,
	keys ...string,
) error {
	if len(
		keys,
	) == 0 {
		return nil
	}

	return s.client.Del(
		ctx,
		keys...,
	).Err()
}

func (s *RedisStore) AcquireCooldown(
	ctx context.Context,
	key string,
	ttl time.Duration,
) (bool, error) {
	return s.client.SetNX(
		ctx,
		key,
		"1",
		ttl,
	).Result()
}

func (s *RedisStore) IncrementWindowCounter(
	ctx context.Context,
	key string,
	window time.Duration,
) (int64, error) {
	count, err := s.client.Incr(
		ctx,
		key,
	).Result()

	if err != nil {
		return 0,
			err
	}

	if count == 1 {
		if err = s.client.Expire(
			ctx,
			key,
			window,
		).Err(); err != nil {
			return 0,
				err
		}
	}

	return count,
		nil
}

func (s *RedisStore) IncrementAttemptCounter(
	ctx context.Context,
	key string,
	ttl time.Duration,
) (int64, error) {
	count, err := s.client.Incr(
		ctx,
		key,
	).Result()

	if err != nil {
		return 0,
			err
	}

	if count == 1 {
		if err = s.client.Expire(
			ctx,
			key,
			ttl,
		).Err(); err != nil {
			return 0,
				err
		}
	}

	return count,
		nil
}
