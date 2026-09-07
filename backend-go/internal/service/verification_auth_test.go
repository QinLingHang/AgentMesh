package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	"example.com/agentmesh-control-plane/internal/security"
	"example.com/agentmesh-control-plane/internal/verification"
)

type fakeAuthRepository struct {
	user *model.User

	refreshCreated int

	passwordReset bool

	passwordHash string

	sessionsRevoked bool
}

func (r *fakeAuthRepository) CreateUser(
	_ context.Context,
	email string,
	hash string,
	name string,
) (*model.User, error) {
	if r.user != nil {
		return nil,
			repository.ErrEmailExists
	}

	r.user = &model.User{
		ID: 42,

		Email: email,

		PasswordHash: hash,

		DisplayName: name,

		Status: "ACTIVE",
	}

	return r.user,
		nil
}

func (r *fakeAuthRepository) UserByEmail(
	_ context.Context,
	email string,
) (*model.User, error) {
	if r.user == nil ||
		r.user.Email != email {
		return nil,
			nil
	}

	return r.user,
		nil
}

func (r *fakeAuthRepository) UserByID(
	_ context.Context,
	id int64,
) (*model.User, error) {
	if r.user == nil ||
		r.user.ID != id {
		return nil,
			nil
	}

	return r.user,
		nil
}

func (r *fakeAuthRepository) CreateRefresh(
	_ context.Context,
	_ int64,
	_ string,
	_ time.Time,
) error {
	r.refreshCreated++

	return nil
}

func (r *fakeAuthRepository) RotateRefresh(
	_ context.Context,
	_ string,
	_ string,
	_ time.Time,
) (int64, error) {
	if r.user == nil {
		return 0,
			repository.ErrInvalidRefreshToken
	}

	return r.user.ID,
		nil
}

func (r *fakeAuthRepository) RevokeRefresh(
	_ context.Context,
	_ string,
) error {
	return nil
}

func (r *fakeAuthRepository) ResetPasswordAndRevokeSessions(
	_ context.Context,
	userID int64,
	hash string,
) error {
	if r.user == nil ||
		r.user.ID != userID {
		return repository.ErrCredentialUserNotFound
	}

	r.passwordReset = true

	r.passwordHash = hash

	r.sessionsRevoked = true

	r.user.PasswordHash = hash

	return nil
}

type fakeVerificationGateway struct {
	policy verification.SendResult

	sendCalls int

	suppressCalls int

	verifyCalls int

	lastScene verification.Scene

	verifyErr error
}

func (v *fakeVerificationGateway) Send(
	_ context.Context,
	_ string,
	scene verification.Scene,
) (verification.SendResult, error) {
	v.sendCalls++

	v.lastScene = scene

	return v.policy,
		nil
}

func (v *fakeVerificationGateway) SuppressSend(
	_ context.Context,
	_ string,
	scene verification.Scene,
) (verification.SendResult, error) {
	v.suppressCalls++

	v.lastScene = scene

	return v.policy,
		nil
}

func (v *fakeVerificationGateway) Verify(
	_ context.Context,
	_ string,
	scene verification.Scene,
	_ string,
) error {
	v.verifyCalls++

	v.lastScene = scene

	return v.verifyErr
}

func (v *fakeVerificationGateway) Policy() verification.SendResult {
	return v.policy
}

func newVerificationAuthTestService(
	repo *fakeAuthRepository,
	gateway *fakeVerificationGateway,
) *VerificationAuthService {
	jwt := security.NewJWTManager(
		"12345678901234567890123456789012",
		"test",
		30*time.Minute,
	)

	auth := NewAuthService(
		repo,
		repo,
		jwt,
		30*24*time.Hour,
	)

	return NewVerificationAuthService(
		repo,
		repo,
		auth,
		gateway,
	)
}

func TestVerificationAuthRegisterFlow(
	t *testing.T,
) {
	repo := &fakeAuthRepository{}

	gateway := &fakeVerificationGateway{
		policy: verification.SendResult{
			ExpiresInSeconds: 300,

			CooldownSeconds: 60,
		},
	}

	service := newVerificationAuthTestService(
		repo,
		gateway,
	)

	result, err := service.SendEmailCode(
		context.Background(),
		"User@Example.com",
		verification.SceneRegister,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if result.CooldownSeconds != 60 ||
		gateway.sendCalls != 1 ||
		gateway.suppressCalls != 0 {
		t.Fatalf(
			"unexpected send behavior: %+v gateway=%+v",
			result,
			gateway,
		)
	}

	authResult, err := service.RegisterWithCode(
		context.Background(),
		"User@Example.com",
		"123456",
		"Test123456",
		"Test User",
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if gateway.lastScene !=
		verification.SceneRegister {
		t.Fatalf(
			"unexpected verify scene: %s",
			gateway.lastScene,
		)
	}

	if authResult.User.Email !=
		"user@example.com" {
		t.Fatalf(
			"unexpected email: %s",
			authResult.User.Email,
		)
	}

	if authResult.AccessToken == "" ||
		authResult.RefreshToken == "" ||
		repo.refreshCreated != 1 {
		t.Fatal(
			"expected auth tokens and refresh persistence",
		)
	}
}

func TestVerificationAuthUnknownLoginUsesSuppressedSend(
	t *testing.T,
) {
	repo := &fakeAuthRepository{}

	gateway := &fakeVerificationGateway{
		policy: verification.SendResult{
			ExpiresInSeconds: 300,

			CooldownSeconds: 60,
		},
	}

	service := newVerificationAuthTestService(
		repo,
		gateway,
	)

	result, err := service.SendEmailCode(
		context.Background(),
		"missing@example.com",
		verification.SceneLogin,
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if result.ExpiresInSeconds != 300 ||
		gateway.sendCalls != 0 ||
		gateway.suppressCalls != 1 {
		t.Fatalf(
			"unknown login must be suppressed: result=%+v gateway=%+v",
			result,
			gateway,
		)
	}
}

func TestVerificationAuthLoginWithCode(
	t *testing.T,
) {
	hash, err := security.HashPassword(
		"OldPassword123",
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	repo := &fakeAuthRepository{
		user: &model.User{
			ID: 7,

			Email: "user@example.com",

			PasswordHash: hash,

			DisplayName: "User",

			Status: "ACTIVE",
		},
	}

	gateway := &fakeVerificationGateway{
		policy: verification.SendResult{
			ExpiresInSeconds: 300,

			CooldownSeconds: 60,
		},
	}

	service := newVerificationAuthTestService(
		repo,
		gateway,
	)

	result, err := service.LoginWithCode(
		context.Background(),
		"user@example.com",
		"123456",
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if gateway.lastScene !=
		verification.SceneLogin ||
		result.AccessToken == "" ||
		result.RefreshToken == "" {
		t.Fatal(
			"verification-code login did not issue auth session",
		)
	}
}

func TestVerificationAuthResetPasswordRevokesSessions(
	t *testing.T,
) {
	oldHash, err := security.HashPassword(
		"OldPassword123",
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	repo := &fakeAuthRepository{
		user: &model.User{
			ID: 9,

			Email: "user@example.com",

			PasswordHash: oldHash,

			DisplayName: "User",

			Status: "ACTIVE",
		},
	}

	gateway := &fakeVerificationGateway{}

	service := newVerificationAuthTestService(
		repo,
		gateway,
	)

	err = service.ResetPassword(
		context.Background(),
		"user@example.com",
		"123456",
		"NewPassword123",
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	if gateway.lastScene !=
		verification.SceneResetPassword {
		t.Fatalf(
			"unexpected reset scene: %s",
			gateway.lastScene,
		)
	}

	if !repo.passwordReset ||
		!repo.sessionsRevoked {
		t.Fatal(
			"password reset must revoke existing refresh sessions",
		)
	}

	if !security.ComparePassword(
		repo.passwordHash,
		"NewPassword123",
	) {
		t.Fatal(
			"new password hash does not match",
		)
	}
}

func TestVerificationAuthMapsInvalidCode(
	t *testing.T,
) {
	repo := &fakeAuthRepository{
		user: &model.User{
			ID: 9,

			Email: "user@example.com",

			Status: "ACTIVE",
		},
	}

	gateway := &fakeVerificationGateway{
		verifyErr: verification.ErrCodeExpired,
	}

	service := newVerificationAuthTestService(
		repo,
		gateway,
	)

	_, err := service.LoginWithCode(
		context.Background(),
		"user@example.com",
		"123456",
	)

	if !errors.Is(
		err,
		ErrVerificationInvalid,
	) {
		t.Fatalf(
			"expected verification error mapping, got %v",
			err,
		)
	}
}
