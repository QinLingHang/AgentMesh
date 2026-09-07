package verification

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

type memoryItem struct {
	value string

	expiresAt time.Time
}

type memoryStore struct {
	mu sync.Mutex

	items map[string]memoryItem

	counters map[string]int64
}

func newMemoryStore() *memoryStore {
	return &memoryStore{
		items: map[string]memoryItem{},

		counters: map[string]int64{},
	}
}

func (s *memoryStore) SetCode(
	_ context.Context,
	key string,
	value string,
	ttl time.Duration,
) error {
	return s.set(
		key,
		value,
		ttl,
	)
}

func (s *memoryStore) GetCode(
	_ context.Context,
	key string,
) (string, error) {
	return s.get(
		key,
	)
}

func (s *memoryStore) SetRecord(
	_ context.Context,
	key string,
	value string,
	ttl time.Duration,
) error {
	return s.set(
		key,
		value,
		ttl,
	)
}

func (s *memoryStore) GetRecord(
	_ context.Context,
	key string,
) (string, error) {
	return s.get(
		key,
	)
}

func (s *memoryStore) set(
	key string,
	value string,
	ttl time.Duration,
) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.items[key] = memoryItem{
		value: value,

		expiresAt: time.Now().
			Add(
				ttl,
			),
	}

	return nil
}

func (s *memoryStore) get(
	key string,
) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	item, ok := s.items[key]

	if !ok ||
		time.Now().After(
			item.expiresAt,
		) {
		delete(
			s.items,
			key,
		)

		return "",
			ErrStoreKeyNotFound
	}

	return item.value,
		nil
}

func (s *memoryStore) Delete(
	_ context.Context,
	keys ...string,
) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, key := range keys {
		delete(
			s.items,
			key,
		)

		delete(
			s.counters,
			key,
		)
	}

	return nil
}

func (s *memoryStore) AcquireCooldown(
	_ context.Context,
	key string,
	ttl time.Duration,
) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	item, ok := s.items[key]

	if ok &&
		time.Now().Before(
			item.expiresAt,
		) {
		return false,
			nil
	}

	s.items[key] = memoryItem{
		value: "1",

		expiresAt: time.Now().
			Add(
				ttl,
			),
	}

	return true,
		nil
}

func (s *memoryStore) IncrementWindowCounter(
	_ context.Context,
	key string,
	_ time.Duration,
) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.counters[key]++

	return s.counters[key],
		nil
}

func (s *memoryStore) IncrementAttemptCounter(
	_ context.Context,
	key string,
	_ time.Duration,
) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.counters[key]++

	return s.counters[key],
		nil
}

type captureSender struct {
	mu sync.Mutex

	lastEmail string

	lastCode string

	lastScene Scene

	sendCount int
}

func (
	s *captureSender,
) SendVerificationCode(
	_ context.Context,
	email string,
	code string,
	scene Scene,
	_ time.Duration,
) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.lastEmail = email

	s.lastCode = code

	s.lastScene = scene

	s.sendCount++

	return nil
}

func newTestService(
	t *testing.T,
) (
	*Service,
	*memoryStore,
	*captureSender,
) {
	t.Helper()

	store := newMemoryStore()

	sender := &captureSender{}

	service, err := NewService(
		store,
		sender,
		Config{
			TTL: 5 * time.Minute,

			Cooldown: 60 * time.Millisecond,

			SendWindow: time.Hour,

			MaxSendsPerWindow: 3,

			MaxVerifyAttempts: 3,

			SendRecordTTL: time.Minute,

			Pepper: "test-verification-pepper-123456",
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	return service,
		store,
		sender
}

func TestSendAndVerifySuccess(
	t *testing.T,
) {
	service,
		_,
		sender :=
		newTestService(
			t,
		)

	ctx := context.Background()

	result, err := service.Send(
		ctx,
		"User@Example.com",
		SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if result.ExpiresInSeconds != 300 {
		t.Fatalf(
			"unexpected ttl: %d",
			result.ExpiresInSeconds,
		)
	}

	if sender.lastEmail !=
		"user@example.com" {
		t.Fatalf(
			"unexpected normalized email: %s",
			sender.lastEmail,
		)
	}

	if len(
		sender.lastCode,
	) != 6 {
		t.Fatalf(
			"unexpected code: %s",
			sender.lastCode,
		)
	}

	if err = service.Verify(
		ctx,
		"user@example.com",
		SceneRegister,
		sender.lastCode,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	err = service.Verify(
		ctx,
		"user@example.com",
		SceneRegister,
		sender.lastCode,
	)

	if !errors.Is(
		err,
		ErrCodeExpired,
	) {
		t.Fatalf(
			"expected one-time code to be gone, got %v",
			err,
		)
	}
}

func TestRecentSendRecord(
	t *testing.T,
) {
	service,
		_,
		_ :=
		newTestService(
			t,
		)

	ctx := context.Background()

	_, err := service.Send(
		ctx,
		"user@example.com",
		SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	record, err := service.RecentSendRecord(
		ctx,
		"user@example.com",
		SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if record.Scene !=
		SceneRegister {
		t.Fatalf(
			"unexpected scene: %s",
			record.Scene,
		)
	}

	if record.MaskedEmail !=
		"us***@example.com" {
		t.Fatalf(
			"unexpected masked email: %s",
			record.MaskedEmail,
		)
	}
}

func TestCodeCannotCrossScenes(
	t *testing.T,
) {
	service,
		_,
		sender :=
		newTestService(
			t,
		)

	ctx := context.Background()

	_, err := service.Send(
		ctx,
		"user@example.com",
		SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	err = service.Verify(
		ctx,
		"user@example.com",
		SceneLogin,
		sender.lastCode,
	)

	if !errors.Is(
		err,
		ErrCodeExpired,
	) {
		t.Fatalf(
			"register code must not work for login: %v",
			err,
		)
	}
}

func TestCooldownPreventsRapidResend(
	t *testing.T,
) {
	service,
		_,
		_ :=
		newTestService(
			t,
		)

	ctx := context.Background()

	_, err := service.Send(
		ctx,
		"user@example.com",
		SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	_, err = service.Send(
		ctx,
		"user@example.com",
		SceneRegister,
	)

	if !errors.Is(
		err,
		ErrCooldown,
	) {
		t.Fatalf(
			"expected cooldown, got %v",
			err,
		)
	}
}

func TestWrongCodeHasAttemptLimit(
	t *testing.T,
) {
	service,
		_,
		_ :=
		newTestService(
			t,
		)

	ctx := context.Background()

	_, err := service.Send(
		ctx,
		"user@example.com",
		SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	for index := 0; index < 3; index++ {
		err = service.Verify(
			ctx,
			"user@example.com",
			SceneRegister,
			"000000",
		)

		if !errors.Is(
			err,
			ErrCodeInvalid,
		) {
			t.Fatalf(
				"expected invalid code on attempt %d, got %v",
				index+1,
				err,
			)
		}
	}

	err = service.Verify(
		ctx,
		"user@example.com",
		SceneRegister,
		"000000",
	)

	if !errors.Is(
		err,
		ErrTooManyAttempts,
	) {
		t.Fatalf(
			"expected attempt limit, got %v",
			err,
		)
	}
}

func TestInvalidEmailRejected(
	t *testing.T,
) {
	service,
		_,
		_ :=
		newTestService(
			t,
		)

	_, err := service.Send(
		context.Background(),
		"not-an-email",
		SceneRegister,
	)

	if !errors.Is(
		err,
		ErrInvalidEmail,
	) {
		t.Fatalf(
			"expected invalid email, got %v",
			err,
		)
	}
}

func TestConstructorRequiresStrongPepper(
	t *testing.T,
) {
	_, err := NewService(
		newMemoryStore(),
		&captureSender{},
		Config{
			Pepper: "short",
		},
	)

	if err == nil {
		t.Fatal(
			"expected short pepper to be rejected",
		)
	}
}
