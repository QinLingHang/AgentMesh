package verification

import (
	"fmt"
	"strings"
	"time"
)

// CommonSMTPConfig builds ready-to-use SMTP settings for common
// personal mailbox providers.
//
// IMPORTANT:
// Password means the SMTP/client authorization code from the mailbox
// security settings, NOT the normal website login password.
func CommonSMTPConfig(
	provider string,
	email string,
	authCode string,
	appName string,
) (SMTPConfig, error) {
	provider = strings.ToLower(
		strings.TrimSpace(
			provider,
		),
	)

	email = strings.TrimSpace(
		email,
	)

	authCode = strings.TrimSpace(
		authCode,
	)

	if email == "" ||
		authCode == "" {
		return SMTPConfig{},
			fmt.Errorf(
				"email and smtp authorization code are required",
			)
	}

	switch provider {
	case "qq":
		return SMTPConfig{
			Host: "smtp.qq.com",

			Port: 465,

			Username: email,

			Password: authCode,

			From: email,

			AppName: appName,

			Mode: SMTPModeImplicitTLS,

			Timeout: 10 * time.Second,
		}, nil

	case "163",
		"netease":
		return SMTPConfig{
			Host: "smtp.163.com",

			Port: 465,

			Username: email,

			Password: authCode,

			From: email,

			AppName: appName,

			Mode: SMTPModeImplicitTLS,

			Timeout: 10 * time.Second,
		}, nil

	case "126":
		return SMTPConfig{
			Host: "smtp.126.com",

			Port: 465,

			Username: email,

			Password: authCode,

			From: email,

			AppName: appName,

			Mode: SMTPModeImplicitTLS,

			Timeout: 10 * time.Second,
		}, nil

	default:
		return SMTPConfig{},
			fmt.Errorf(
				"unsupported common smtp provider: %s",
				provider,
			)
	}
}
