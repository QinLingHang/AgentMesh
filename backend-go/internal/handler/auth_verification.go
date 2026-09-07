package handler

import (
	"errors"
	"log"
	"net/http"
	"time"

	"example.com/agentmesh-control-plane/internal/service"
	"example.com/agentmesh-control-plane/internal/verification"

	"github.com/gin-gonic/gin"
)

type VerificationAuthHandler struct {
	s *service.VerificationAuthService

	cookie string

	secure bool

	maxAge int
}

func NewVerificationAuthHandler(
	s *service.VerificationAuthService,
	cookie string,
	secure bool,
	ttl time.Duration,
) *VerificationAuthHandler {
	return &VerificationAuthHandler{
		s: s,

		cookie: cookie,

		secure: secure,

		maxAge: int(
			ttl.Seconds(),
		),
	}
}

type emailCodeReq struct {
	Email string `json:"email" binding:"required,email"`

	Scene string `json:"scene" binding:"required,oneof=register login reset_password"`
}

type verifiedRegisterReq struct {
	Email string `json:"email" binding:"required,email"`

	Code string `json:"code" binding:"required,len=6,numeric"`

	Password string `json:"password" binding:"required"`

	DisplayName string `json:"displayName" binding:"required"`
}

type codeLoginReq struct {
	Email string `json:"email" binding:"required,email"`

	Code string `json:"code" binding:"required,len=6,numeric"`
}

type resetPasswordReq struct {
	Email string `json:"email" binding:"required,email"`

	Code string `json:"code" binding:"required,len=6,numeric"`

	NewPassword string `json:"newPassword" binding:"required"`
}

func (h *VerificationAuthHandler) setCookie(
	c *gin.Context,
	value string,
) {
	c.SetSameSite(
		http.SameSiteLaxMode,
	)

	c.SetCookie(
		h.cookie,
		value,
		h.maxAge,
		"/api/auth",
		"",
		h.secure,
		true,
	)
}

func (h *VerificationAuthHandler) clearCookie(
	c *gin.Context,
) {
	c.SetSameSite(
		http.SameSiteLaxMode,
	)

	c.SetCookie(
		h.cookie,
		"",
		-1,
		"/api/auth",
		"",
		h.secure,
		true,
	)
}

func (h *VerificationAuthHandler) SendEmailCode(
	c *gin.Context,
) {
	var req emailCodeReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40013,
			"邮箱或验证码场景不合法",
		)

		return
	}

	result, err := h.s.SendEmailCode(
		c,
		req.Email,
		verification.Scene(
			req.Scene,
		),
	)

	switch {
	case errors.Is(
		err,
		service.ErrEmailExists,
	):
		fail(
			c,
			http.StatusConflict,
			40901,
			"邮箱已注册",
		)

		return

	case errors.Is(
		err,
		service.ErrVerificationCooldown,
	):
		fail(
			c,
			http.StatusTooManyRequests,
			42911,
			"验证码发送过于频繁，请稍后再试",
		)

		return

	case errors.Is(
		err,
		service.ErrVerificationSendLimit,
	):
		fail(
			c,
			http.StatusTooManyRequests,
			42912,
			"验证码发送次数已达上限，请稍后再试",
		)

		return

	case errors.Is(
		err,
		service.ErrInvalidInput,
	):
		fail(
			c,
			http.StatusBadRequest,
			40013,
			"邮箱或验证码场景不合法",
		)

		return

	case err != nil:
		log.Printf(
			"[auth verification] send code failed scene=%s: %v",
			req.Scene,
			err,
		)

		fail(
			c,
			http.StatusServiceUnavailable,
			50311,
			"验证码服务暂时不可用，请稍后重试",
		)

		return
	}

	ok(
		c,
		result,
	)
}

func (h *VerificationAuthHandler) RegisterVerified(
	c *gin.Context,
) {
	var req verifiedRegisterReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40014,
			"注册参数不合法",
		)

		return
	}

	result, err := h.s.RegisterWithCode(
		c,
		req.Email,
		req.Code,
		req.Password,
		req.DisplayName,
	)

	switch {
	case errors.Is(
		err,
		service.ErrEmailExists,
	):
		fail(
			c,
			http.StatusConflict,
			40901,
			"邮箱已注册",
		)

		return

	case errors.Is(
		err,
		service.ErrVerificationInvalid,
	):
		fail(
			c,
			http.StatusBadRequest,
			40015,
			"验证码无效、已过期或尝试次数过多",
		)

		return

	case errors.Is(
		err,
		service.ErrInvalidInput,
	):
		fail(
			c,
			http.StatusBadRequest,
			40014,
			"注册参数不合法",
		)

		return

	case err != nil:
		log.Printf(
			"[auth verification] verified register failed: %v",
			err,
		)

		fail(
			c,
			http.StatusInternalServerError,
			50011,
			"账户服务暂时不可用，请稍后重试",
		)

		return
	}

	h.setCookie(
		c,
		result.RefreshToken,
	)

	c.JSON(
		http.StatusCreated,
		gin.H{
			"code": 0,

			"message": "success",

			"data": authData(
				result,
			),
		},
	)
}

func (h *VerificationAuthHandler) LoginWithCode(
	c *gin.Context,
) {
	var req codeLoginReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40016,
			"登录参数不合法",
		)

		return
	}

	result, err := h.s.LoginWithCode(
		c,
		req.Email,
		req.Code,
	)

	if errors.Is(
		err,
		service.ErrInvalidCredentials,
	) ||
		errors.Is(
			err,
			service.ErrVerificationInvalid,
		) {
		fail(
			c,
			http.StatusUnauthorized,
			40102,
			"邮箱或验证码无效",
		)

		return
	}

	if err != nil {
		log.Printf(
			"[auth verification] code login failed: %v",
			err,
		)

		fail(
			c,
			http.StatusInternalServerError,
			50012,
			"账户服务暂时不可用，请稍后重试",
		)

		return
	}

	h.setCookie(
		c,
		result.RefreshToken,
	)

	ok(
		c,
		authData(
			result,
		),
	)
}

func (h *VerificationAuthHandler) ResetPassword(
	c *gin.Context,
) {
	var req resetPasswordReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40017,
			"重置密码参数不合法",
		)

		return
	}

	err := h.s.ResetPassword(
		c,
		req.Email,
		req.Code,
		req.NewPassword,
	)

	if errors.Is(
		err,
		service.ErrVerificationInvalid,
	) {
		fail(
			c,
			http.StatusBadRequest,
			40018,
			"验证码无效、已过期或尝试次数过多",
		)

		return
	}

	if errors.Is(
		err,
		service.ErrInvalidInput,
	) {
		fail(
			c,
			http.StatusBadRequest,
			40017,
			"新密码不符合要求",
		)

		return
	}

	if err != nil {
		log.Printf(
			"[auth verification] password reset failed: %v",
			err,
		)

		fail(
			c,
			http.StatusInternalServerError,
			50013,
			"账户服务暂时不可用，请稍后重试",
		)

		return
	}

	// Password reset revokes every refresh token in the database.
	// Also clear the current browser cookie immediately.
	h.clearCookie(
		c,
	)

	ok(
		c,
		nil,
	)
}
