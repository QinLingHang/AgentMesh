package verification

import (
	"errors"
	"strings"
	"time"
)

// Scene identifies why a verification code is sent.
//
// Scene isolation prevents a code issued for registration
// from being reused for login or password reset.
type Scene string

const (
	SceneRegister      Scene = "register"
	SceneLogin         Scene = "login"
	SceneResetPassword Scene = "reset_password"
)

var (
	ErrInvalidEmail    = errors.New("invalid email")
	ErrInvalidScene    = errors.New("invalid verification scene")
	ErrCooldown        = errors.New("verification code cooldown")
	ErrSendLimit       = errors.New("verification code send limit reached")
	ErrCodeExpired     = errors.New("verification code expired")
	ErrCodeInvalid     = errors.New("verification code invalid")
	ErrTooManyAttempts = errors.New("too many verification attempts")
)

type Config struct {
	TTL time.Duration

	Cooldown time.Duration

	SendWindow time.Duration

	MaxSendsPerWindow int64

	MaxVerifyAttempts int64

	// SendRecordTTL controls how long a lightweight send record is kept.
	//
	// Default: 1 minute.
	SendRecordTTL time.Duration

	// Pepper is a server-side secret used when hashing verification codes.
	//
	// Do not hard-code the production value in source code.
	Pepper string
}

func (c Config) withDefaults() Config {
	if c.TTL <= 0 {
		c.TTL = 5 * time.Minute
	}

	if c.Cooldown <= 0 {
		c.Cooldown = 60 * time.Second
	}

	if c.SendWindow <= 0 {
		c.SendWindow = time.Hour
	}

	if c.MaxSendsPerWindow <= 0 {
		c.MaxSendsPerWindow = 10
	}

	if c.MaxVerifyAttempts <= 0 {
		c.MaxVerifyAttempts = 5
	}

	if c.SendRecordTTL <= 0 {
		c.SendRecordTTL = time.Minute
	}

	return c
}

type SendResult struct {
	ExpiresInSeconds int64 `json:"expiresInSeconds"`

	CooldownSeconds int64 `json:"cooldownSeconds"`
}

type SendRecord struct {
	MaskedEmail string `json:"maskedEmail"`

	Scene Scene `json:"scene"`

	SentAt time.Time `json:"sentAt"`
}

func normalizeScene(
	scene Scene,
) Scene {
	return Scene(
		strings.ToLower(
			strings.TrimSpace(
				string(scene),
			),
		),
	)
}

func validScene(
	scene Scene,
) bool {
	switch normalizeScene(
		scene,
	) {
	case SceneRegister,
		SceneLogin,
		SceneResetPassword:
		return true

	default:
		return false
	}
}
