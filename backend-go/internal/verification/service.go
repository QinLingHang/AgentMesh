package verification

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/mail"
	"strings"
	"time"
)

type Service struct {
	store Store

	sender EmailSender

	cfg Config
}

func NewService(
	store Store,
	sender EmailSender,
	cfg Config,
) (*Service, error) {
	if store == nil {
		return nil, fmt.Errorf(
			"verification store is required",
		)
	}

	if sender == nil {
		return nil, fmt.Errorf(
			"verification email sender is required",
		)
	}

	cfg = cfg.withDefaults()

	if len(
		strings.TrimSpace(
			cfg.Pepper,
		),
	) < 16 {
		return nil, fmt.Errorf(
			"verification pepper must be at least 16 characters",
		)
	}

	return &Service{
		store: store,

		sender: sender,

		cfg: cfg,
	}, nil
}

func (s *Service) Send(
	ctx context.Context,
	email string,
	scene Scene,
) (SendResult, error) {
	email, err := normalizeEmail(
		email,
	)

	if err != nil {
		return SendResult{},
			err
	}

	scene = normalizeScene(
		scene,
	)

	if !validScene(
		scene,
	) {
		return SendResult{},
			ErrInvalidScene
	}

	keys := buildKeys(
		email,
		scene,
	)

	acquired, err := s.store.AcquireCooldown(
		ctx,
		keys.cooldown,
		s.cfg.Cooldown,
	)

	if err != nil {
		return SendResult{},
			err
	}

	if !acquired {
		return SendResult{},
			ErrCooldown
	}

	sendCount, err := s.store.IncrementWindowCounter(
		ctx,
		keys.sendWindow,
		s.cfg.SendWindow,
	)

	if err != nil {
		_ = s.store.Delete(
			ctx,
			keys.cooldown,
		)

		return SendResult{},
			err
	}

	if sendCount >
		s.cfg.MaxSendsPerWindow {
		_ = s.store.Delete(
			ctx,
			keys.cooldown,
		)

		return SendResult{},
			ErrSendLimit
	}

	code, err := generateNumericCode(
		6,
	)

	if err != nil {
		_ = s.store.Delete(
			ctx,
			keys.cooldown,
		)

		return SendResult{},
			err
	}

	codeHash := s.hashCode(
		email,
		scene,
		code,
	)

	if err = s.store.SetCode(
		ctx,
		keys.code,
		codeHash,
		s.cfg.TTL,
	); err != nil {
		_ = s.store.Delete(
			ctx,
			keys.cooldown,
		)

		return SendResult{},
			err
	}

	if err = s.sender.SendVerificationCode(
		ctx,
		email,
		code,
		scene,
		s.cfg.TTL,
	); err != nil {
		_ = s.store.Delete(
			ctx,
			keys.code,
			keys.cooldown,
		)

		return SendResult{},
			err
	}

	// Keep a lightweight one-minute send record.
	//
	// It deliberately does NOT contain the verification code.
	//
	// This is useful for:
	// - local debugging
	// - UI send-state inspection
	// - short-lived operational visibility
	//
	// Failure to write this auxiliary record must not turn a
	// successfully delivered email into an API failure.
	record := SendRecord{
		MaskedEmail: maskEmail(
			email,
		),

		Scene: scene,

		SentAt: time.Now().
			UTC(),
	}

	if raw, marshalErr := json.Marshal(
		record,
	); marshalErr == nil {
		_ = s.store.SetRecord(
			ctx,
			keys.sendRecord,
			string(
				raw,
			),
			s.cfg.SendRecordTTL,
		)
	}

	return SendResult{
		ExpiresInSeconds: int64(
			s.cfg.TTL.Seconds(),
		),

		CooldownSeconds: int64(
			s.cfg.Cooldown.Seconds(),
		),
	}, nil
}

func (s *Service) RecentSendRecord(
	ctx context.Context,
	email string,
	scene Scene,
) (*SendRecord, error) {
	email, err := normalizeEmail(
		email,
	)

	if err != nil {
		return nil,
			err
	}

	scene = normalizeScene(
		scene,
	)

	if !validScene(
		scene,
	) {
		return nil,
			ErrInvalidScene
	}

	raw, err := s.store.GetRecord(
		ctx,
		buildKeys(
			email,
			scene,
		).sendRecord,
	)

	if errors.Is(
		err,
		ErrStoreKeyNotFound,
	) {
		return nil,
			ErrStoreKeyNotFound
	}

	if err != nil {
		return nil,
			err
	}

	var record SendRecord

	if err = json.Unmarshal(
		[]byte(
			raw,
		),
		&record,
	); err != nil {
		return nil,
			err
	}

	return &record,
		nil
}

func (s *Service) Verify(
	ctx context.Context,
	email string,
	scene Scene,
	code string,
) error {
	email, err := normalizeEmail(
		email,
	)

	if err != nil {
		return err
	}

	scene = normalizeScene(
		scene,
	)

	if !validScene(
		scene,
	) {
		return ErrInvalidScene
	}

	code = strings.TrimSpace(
		code,
	)

	if len(
		code,
	) != 6 ||
		!digitsOnly(
			code,
		) {
		return ErrCodeInvalid
	}

	keys := buildKeys(
		email,
		scene,
	)

	storedHash, err := s.store.GetCode(
		ctx,
		keys.code,
	)

	if errors.Is(
		err,
		ErrStoreKeyNotFound,
	) {
		return ErrCodeExpired
	}

	if err != nil {
		return err
	}

	attempts, err := s.store.IncrementAttemptCounter(
		ctx,
		keys.attempts,
		s.cfg.TTL,
	)

	if err != nil {
		return err
	}

	if attempts >
		s.cfg.MaxVerifyAttempts {
		_ = s.store.Delete(
			ctx,
			keys.code,
			keys.attempts,
		)

		return ErrTooManyAttempts
	}

	expectedHash := s.hashCode(
		email,
		scene,
		code,
	)

	if subtle.ConstantTimeCompare(
		[]byte(
			storedHash,
		),
		[]byte(
			expectedHash,
		),
	) != 1 {
		return ErrCodeInvalid
	}

	return s.store.Delete(
		ctx,
		keys.code,
		keys.attempts,
	)
}

func (s *Service) hashCode(
	email string,
	scene Scene,
	code string,
) string {
	mac := hmac.New(
		sha256.New,
		[]byte(
			s.cfg.Pepper,
		),
	)

	_, _ = mac.Write(
		[]byte(
			email +
				"|" +
				string(scene) +
				"|" +
				code,
		),
	)

	return hex.EncodeToString(
		mac.Sum(
			nil,
		),
	)
}

type keySet struct {
	code string

	cooldown string

	sendWindow string

	attempts string

	sendRecord string
}

func buildKeys(
	email string,
	scene Scene,
) keySet {
	sum := sha256.Sum256(
		[]byte(
			email,
		),
	)

	emailKey := hex.EncodeToString(
		sum[:],
	)

	prefix := "auth:verify:" +
		string(scene) +
		":" +
		emailKey

	return keySet{
		code: prefix + ":code",

		cooldown: prefix + ":cooldown",

		sendWindow: prefix + ":send_window",

		attempts: prefix + ":attempts",

		sendRecord: prefix + ":sent",
	}
}

func normalizeEmail(
	value string,
) (string, error) {
	value = strings.ToLower(
		strings.TrimSpace(
			value,
		),
	)

	if value == "" ||
		len(
			value,
		) > 254 {
		return "",
			ErrInvalidEmail
	}

	address, err := mail.ParseAddress(
		value,
	)

	if err != nil ||
		!strings.EqualFold(
			address.Address,
			value,
		) {
		return "",
			ErrInvalidEmail
	}

	return value,
		nil
}

func generateNumericCode(
	length int,
) (string, error) {
	if length <= 0 {
		return "",
			fmt.Errorf(
				"invalid code length",
			)
	}

	var builder strings.Builder

	builder.Grow(
		length,
	)

	for index := 0; index < length; index++ {
		value, err := rand.Int(
			rand.Reader,
			big.NewInt(
				10,
			),
		)

		if err != nil {
			return "",
				err
		}

		builder.WriteByte(
			byte(
				'0' +
					value.Int64(),
			),
		)
	}

	return builder.String(),
		nil
}

func digitsOnly(
	value string,
) bool {
	for _, r := range value {
		if r < '0' ||
			r > '9' {
			return false
		}
	}

	return true
}

func maskEmail(
	email string,
) string {
	parts := strings.Split(
		email,
		"@",
	)

	if len(parts) != 2 {
		return "***"
	}

	local := parts[0]

	if len(local) <= 2 {
		local = local[:1] +
			"***"
	} else {
		local = local[:2] +
			"***"
	}

	return local +
		"@" +
		parts[1]
}
