package router

import "github.com/gin-gonic/gin"

func registerAuthRoutes(
	api *gin.RouterGroup,
	deps Dependencies,
) {
	// -----------------------------------------------------
	// Password login remains supported.
	//
	// Password-only registration is intentionally removed.
	// New accounts must verify ownership of the email first.
	// -----------------------------------------------------

	api.POST(
		"/auth/login",
		deps.AuthHandler.Login,
	)

	api.POST(
		"/auth/refresh",
		deps.AuthHandler.Refresh,
	)

	api.POST(
		"/auth/logout",
		deps.AuthHandler.Logout,
	)

	// -----------------------------------------------------
	// Verification-code auth.
	// -----------------------------------------------------

	api.POST(
		"/auth/email/code",
		deps.VerificationAuthHandler.SendEmailCode,
	)

	api.POST(
		"/auth/register/verify",
		deps.VerificationAuthHandler.RegisterVerified,
	)

	api.POST(
		"/auth/login/code",
		deps.VerificationAuthHandler.LoginWithCode,
	)

	api.POST(
		"/auth/password/reset",
		deps.VerificationAuthHandler.ResetPassword,
	)
}

func registerCurrentUserRoutes(
	protected *gin.RouterGroup,
	deps Dependencies,
) {
	protected.GET(
		"/me",
		deps.AuthHandler.Me,
	)
}
