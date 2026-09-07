package verification

import (
	"context"
	"encoding/json"
	"time"
)

// NormalizeEmail exposes the same normalization rule used internally by
// the verification domain so callers do not accidentally implement a
// second, slightly different email normalization policy.
func NormalizeEmail(
	value string,
) (string, error) {
	return normalizeEmail(
		value,
	)
}

// IsValidScene lets application services validate a scene before they
// decide whether a real email should be sent.
func IsValidScene(
	scene Scene,
) bool {
	return validScene(
		normalizeScene(
			scene,
		),
	)
}

// Policy returns the public timing contract exposed by the send API.
func (s *Service) Policy() SendResult {
	return SendResult{
		ExpiresInSeconds: int64(
			s.cfg.TTL.Seconds(),
		),

		CooldownSeconds: int64(
			s.cfg.Cooldown.Seconds(),
		),
	}
}

// SuppressSend applies the same cooldown / send-window policy and writes
// the same short-lived send record, but does not create a verification
// code and does not send an email.
//
// It is used for login / reset requests targeting an unknown account so
// the public API can return the same generic response without turning
// the endpoint into an email-spam relay.
func (s *Service) SuppressSend(
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

	record := SendRecord{
		MaskedEmail: maskEmail(
			email,
		),

		Scene: scene,

		SentAt: time.Now().UTC(),
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

	return s.Policy(),
		nil
}
