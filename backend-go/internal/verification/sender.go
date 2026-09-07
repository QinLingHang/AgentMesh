package verification

import (
	"context"
	"crypto/tls"
	"fmt"
	"log"
	"mime"
	"net"
	"net/smtp"
	"strconv"
	"strings"
	"time"
)

type EmailSender interface {
	SendVerificationCode(
		ctx context.Context,
		to string,
		code string,
		scene Scene,
		expiresIn time.Duration,
	) error
}

type ConsoleEmailSender struct{}

func NewConsoleEmailSender() *ConsoleEmailSender {
	return &ConsoleEmailSender{}
}

func (s *ConsoleEmailSender) SendVerificationCode(
	_ context.Context,
	to string,
	code string,
	scene Scene,
	expiresIn time.Duration,
) error {
	log.Printf(
		"[DEV EMAIL] to=%s scene=%s code=%s expires=%s",
		to,
		scene,
		code,
		expiresIn,
	)

	return nil
}

type SMTPMode string

const (
	SMTPModeImplicitTLS SMTPMode = "implicit_tls"

	SMTPModeSTARTTLS SMTPMode = "starttls"
)

type SMTPConfig struct {
	Host string

	Port int

	Username string

	// Password should be the mailbox SMTP authorization code
	// when the provider requires one.
	Password string

	From string

	AppName string

	Mode SMTPMode

	Timeout time.Duration
}

func NewSMTPEmailSender(
	cfg SMTPConfig,
) *SMTPEmailSender {
	if strings.TrimSpace(
		cfg.AppName,
	) == "" {
		cfg.AppName = "AgentMesh"
	}

	if cfg.Timeout <= 0 {
		cfg.Timeout = 10 * time.Second
	}

	if cfg.Mode == "" {
		cfg.Mode = SMTPModeImplicitTLS
	}

	return &SMTPEmailSender{
		cfg: cfg,
	}
}

type SMTPEmailSender struct {
	cfg SMTPConfig
}

func (s *SMTPEmailSender) SendVerificationCode(
	ctx context.Context,
	to string,
	code string,
	scene Scene,
	expiresIn time.Duration,
) error {
	message := buildVerificationMessage(
		s.cfg,
		to,
		code,
		scene,
		expiresIn,
	)

	switch s.cfg.Mode {
	case SMTPModeImplicitTLS:
		return s.sendImplicitTLS(
			ctx,
			to,
			message,
		)

	case SMTPModeSTARTTLS:
		return s.sendSTARTTLS(
			ctx,
			to,
			message,
		)

	default:
		return fmt.Errorf(
			"unsupported smtp mode: %s",
			s.cfg.Mode,
		)
	}
}

func (s *SMTPEmailSender) sendImplicitTLS(
	ctx context.Context,
	to string,
	message []byte,
) error {
	host := strings.TrimSpace(
		s.cfg.Host,
	)

	if host == "" ||
		s.cfg.Port <= 0 ||
		strings.TrimSpace(
			s.cfg.From,
		) == "" {
		return fmt.Errorf(
			"invalid smtp configuration",
		)
	}

	address := net.JoinHostPort(
		host,
		strconv.Itoa(
			s.cfg.Port,
		),
	)

	dialer := &net.Dialer{
		Timeout: s.cfg.Timeout,
	}

	conn, err := tls.DialWithDialer(
		dialer,
		"tcp",
		address,
		&tls.Config{
			ServerName: host,

			MinVersion: tls.VersionTLS12,
		},
	)

	if err != nil {
		return err
	}

	defer conn.Close()

	select {
	case <-ctx.Done():
		return ctx.Err()

	default:
	}

	client, err := smtp.NewClient(
		conn,
		host,
	)

	if err != nil {
		return err
	}

	defer client.Close()

	if err = s.authenticate(
		client,
		host,
	); err != nil {
		return err
	}

	return sendSMTPData(
		client,
		s.cfg.From,
		to,
		message,
	)
}

func (s *SMTPEmailSender) sendSTARTTLS(
	ctx context.Context,
	to string,
	message []byte,
) error {
	host := strings.TrimSpace(
		s.cfg.Host,
	)

	if host == "" ||
		s.cfg.Port <= 0 ||
		strings.TrimSpace(
			s.cfg.From,
		) == "" {
		return fmt.Errorf(
			"invalid smtp configuration",
		)
	}

	address := net.JoinHostPort(
		host,
		strconv.Itoa(
			s.cfg.Port,
		),
	)

	dialer := &net.Dialer{
		Timeout: s.cfg.Timeout,
	}

	conn, err := dialer.DialContext(
		ctx,
		"tcp",
		address,
	)

	if err != nil {
		return err
	}

	defer conn.Close()

	client, err := smtp.NewClient(
		conn,
		host,
	)

	if err != nil {
		return err
	}

	defer client.Close()

	if err = client.StartTLS(
		&tls.Config{
			ServerName: host,

			MinVersion: tls.VersionTLS12,
		},
	); err != nil {
		return err
	}

	if err = s.authenticate(
		client,
		host,
	); err != nil {
		return err
	}

	return sendSMTPData(
		client,
		s.cfg.From,
		to,
		message,
	)
}

func (s *SMTPEmailSender) authenticate(
	client *smtp.Client,
	host string,
) error {
	username := strings.TrimSpace(
		s.cfg.Username,
	)

	if username == "" {
		return nil
	}

	auth := smtp.PlainAuth(
		"",
		username,
		s.cfg.Password,
		host,
	)

	return client.Auth(
		auth,
	)
}

func sendSMTPData(
	client *smtp.Client,
	from string,
	to string,
	message []byte,
) error {
	if err := client.Mail(
		from,
	); err != nil {
		return err
	}

	if err := client.Rcpt(
		to,
	); err != nil {
		return err
	}

	writer, err := client.Data()

	if err != nil {
		return err
	}

	if _, err = writer.Write(
		message,
	); err != nil {
		_ = writer.Close()

		return err
	}

	if err = writer.Close(); err != nil {
		return err
	}

	return client.Quit()
}

func buildVerificationMessage(
	cfg SMTPConfig,
	to string,
	code string,
	scene Scene,
	expiresIn time.Duration,
) []byte {
	appName := strings.TrimSpace(
		cfg.AppName,
	)

	if appName == "" {
		appName = "AgentMesh"
	}

	subject := mime.QEncoding.Encode(
		"UTF-8",
		fmt.Sprintf(
			"%s 验证码",
			appName,
		),
	)

	minutes := int(
		expiresIn.Round(
			time.Minute,
		) / time.Minute,
	)

	if minutes <= 0 {
		minutes = 5
	}

	body := fmt.Sprintf(
		"你正在进行 %s。\r\n\r\n验证码：%s\r\n\r\n验证码 %d 分钟内有效，请勿转发给他人。\r\n",
		sceneDisplayName(
			scene,
		),
		code,
		minutes,
	)

	headers := []string{
		"From: " + cfg.From,
		"To: " + to,
		"Subject: " + subject,
		"MIME-Version: 1.0",
		"Content-Type: text/plain; charset=UTF-8",
	}

	raw := strings.Join(
		headers,
		"\r\n",
	) +
		"\r\n\r\n" +
		body

	return []byte(
		raw,
	)
}

func sceneDisplayName(
	scene Scene,
) string {
	switch normalizeScene(
		scene,
	) {
	case SceneRegister:
		return "AgentMesh 账号注册"

	case SceneLogin:
		return "AgentMesh 验证码登录"

	case SceneResetPassword:
		return "AgentMesh 密码重置"

	default:
		return "AgentMesh 身份验证"
	}
}
