package service

import (
	"context"
	"errors"
	"strings"

	"example.com/agentmesh-control-plane/internal/repository"
	"example.com/agentmesh-control-plane/internal/security"
	"example.com/agentmesh-control-plane/internal/verification"
)

var ErrVerificationInvalid = errors.New(
	"verification code invalid or expired",
)

var ErrVerificationCooldown = errors.New(
	"verification code cooldown",
)

var ErrVerificationSendLimit = errors.New(
	"verification code send limit reached",
)

// VerificationGateway is the application-facing verification contract.
//
// Keeping this as an interface makes Auth integration unit-testable without
// requiring a real Redis server or SMTP provider.
type VerificationGateway interface {
	Send(
		context.Context,
		string,
		verification.Scene,
	) (verification.SendResult, error)

	SuppressSend(
		context.Context,
		string,
		verification.Scene,
	) (verification.SendResult, error)

	Verify(
		context.Context,
		string,
		verification.Scene,
		string,
	) error

	Policy() verification.SendResult
}

type VerificationAuthService struct {
	users repository.UserRepository

	credentials repository.CredentialRepository

	auth *AuthService

	verification VerificationGateway
}

func NewVerificationAuthService(
	users repository.UserRepository,
	credentials repository.CredentialRepository,
	auth *AuthService,
	verificationService VerificationGateway,
) *VerificationAuthService {
	return &VerificationAuthService{
		users: users,

		credentials: credentials,

		auth: auth,

		verification: verificationService,
	}
}

// SendEmailCode sends a real code only when the requested scene makes
// sense for the current account state.
//
// register:
//
//	existing account -> explicit conflict
//
// login / reset_password:
//
//	missing account -> generic success + suppressed send
//
// The latter avoids turning the endpoint into a simple account-enumeration
// API while also preventing emails from being sent to arbitrary unknown
// addresses.
func (s *VerificationAuthService) SendEmailCode(
	ctx context.Context,
	email string,
	scene verification.Scene,
) (verification.SendResult, error) {
	normalizedEmail, err := verification.NormalizeEmail(
		email,
	)

	if err != nil ||
		!verification.IsValidScene(
			scene,
		) {
		return verification.SendResult{},
			ErrInvalidInput
	}

	scene = verification.Scene(
		strings.ToLower(
			strings.TrimSpace(
				string(scene),
			),
		),
	)

	user, err := s.users.UserByEmail(
		ctx,
		normalizedEmail,
	)

	if err != nil {
		return verification.SendResult{},
			err
	}

	switch scene {
	case verification.SceneRegister:
		if user != nil {
			return verification.SendResult{},
				ErrEmailExists
		}

		result, sendErr := s.verification.Send(
			ctx,
			normalizedEmail,
			scene,
		)

		return result,
			mapVerificationError(
				sendErr,
			)

	case verification.SceneLogin,
		verification.SceneResetPassword:
		if user == nil ||
			user.Status != "ACTIVE" {
			result, suppressErr := s.verification.SuppressSend(
				ctx,
				normalizedEmail,
				scene,
			)

			return result,
				mapVerificationError(
					suppressErr,
				)
		}

		result, sendErr := s.verification.Send(
			ctx,
			normalizedEmail,
			scene,
		)

		return result,
			mapVerificationError(
				sendErr,
			)

	default:
		return verification.SendResult{},
			ErrInvalidInput
	}
}

func (s *VerificationAuthService) RegisterWithCode(
	ctx context.Context,
	email string,
	code string,
	password string,
	displayName string,
) (*AuthResult, error) {
	normalizedEmail, err := verification.NormalizeEmail(
		email,
	)

	if err != nil {
		return nil,
			ErrInvalidInput
	}

	displayName = strings.TrimSpace(
		displayName,
	)

	if displayName == "" {
		return nil,
			ErrInvalidInput
	}

	passwordHash, err := security.HashPassword(
		password,
	)

	if err != nil {
		return nil,
			ErrInvalidInput
	}

	existing, err := s.users.UserByEmail(
		ctx,
		normalizedEmail,
	)

	if err != nil {
		return nil,
			err
	}

	if existing != nil {
		return nil,
			ErrEmailExists
	}

	if err = s.verification.Verify(
		ctx,
		normalizedEmail,
		verification.SceneRegister,
		code,
	); err != nil {
		return nil,
			mapVerificationError(
				err,
			)
	}

	user, err := s.users.CreateUser(
		ctx,
		normalizedEmail,
		passwordHash,
		displayName,
	)

	if errors.Is(
		err,
		repository.ErrEmailExists,
	) {
		return nil,
			ErrEmailExists
	}

	if err != nil {
		return nil,
			err
	}

	return s.auth.issue(
		ctx,
		user,
	)
}

func (s *VerificationAuthService) LoginWithCode(
	ctx context.Context,
	email string,
	code string,
) (*AuthResult, error) {
	normalizedEmail, err := verification.NormalizeEmail(
		email,
	)

	if err != nil {
		return nil,
			ErrInvalidCredentials
	}

	user, err := s.users.UserByEmail(
		ctx,
		normalizedEmail,
	)

	if err != nil {
		return nil,
			err
	}

	if user == nil ||
		user.Status != "ACTIVE" {
		return nil,
			ErrInvalidCredentials
	}

	if err = s.verification.Verify(
		ctx,
		normalizedEmail,
		verification.SceneLogin,
		code,
	); err != nil {
		return nil,
			mapVerificationError(
				err,
			)
	}

	return s.auth.issue(
		ctx,
		user,
	)
}

func (s *VerificationAuthService) ResetPassword(
	ctx context.Context,
	email string,
	code string,
	newPassword string,
) error {
	normalizedEmail, err := verification.NormalizeEmail(
		email,
	)

	if err != nil {
		return ErrVerificationInvalid
	}

	passwordHash, err := security.HashPassword(
		newPassword,
	)

	if err != nil {
		return ErrInvalidInput
	}

	user, err := s.users.UserByEmail(
		ctx,
		normalizedEmail,
	)

	if err != nil {
		return err
	}

	if user == nil ||
		user.Status != "ACTIVE" {
		return ErrVerificationInvalid
	}

	if err = s.verification.Verify(
		ctx,
		normalizedEmail,
		verification.SceneResetPassword,
		code,
	); err != nil {
		return mapVerificationError(
			err,
		)
	}

	if err = s.credentials.ResetPasswordAndRevokeSessions(
		ctx,
		user.ID,
		passwordHash,
	); errors.Is(
		err,
		repository.ErrCredentialUserNotFound,
	) {
		return ErrVerificationInvalid
	}

	return err
}

func mapVerificationError(
	err error,
) error {
	if err == nil {
		return nil
	}

	switch {
	case errors.Is(
		err,
		verification.ErrInvalidEmail,
	),
		errors.Is(
			err,
			verification.ErrInvalidScene,
		):
		return ErrInvalidInput

	case errors.Is(
		err,
		verification.ErrCooldown,
	):
		return ErrVerificationCooldown

	case errors.Is(
		err,
		verification.ErrSendLimit,
	):
		return ErrVerificationSendLimit

	case errors.Is(
		err,
		verification.ErrCodeExpired,
	),
		errors.Is(
			err,
			verification.ErrCodeInvalid,
		),
		errors.Is(
			err,
			verification.ErrTooManyAttempts,
		):
		return ErrVerificationInvalid

	default:
		return err
	}
}
