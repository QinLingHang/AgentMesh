package config

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

type MySQL struct {
	Host string

	Port string

	Database string

	User string

	Password string
}

type Redis struct {
	Addr string

	Password string

	DB int
}

type JWT struct {
	Secret string

	Issuer string

	AccessTTL time.Duration

	RefreshTTL time.Duration
}

type Email struct {
	Provider string

	Address string

	AuthCode string

	AppName string
}

type Knowledge struct {
	StorageRoot string

	MaxUploadBytes int64
}

type DurableRuntime struct {
	Enabled                 bool
	ControlPlaneBaseURL     string
	DispatcherID            string
	DispatcherLeaseDuration time.Duration
	PollInterval            time.Duration
	LeaseDuration           time.Duration
	ExecutionLeaseDuration  time.Duration
	WorkerStaleAfter        time.Duration
	AcceptanceTimeout       time.Duration
	RetryBackoff            time.Duration
	JobDeadline             time.Duration
	MaxAttempts             int
	MaxQueueDepth           int
	CircuitFailureThreshold int
	CircuitOpenFor          time.Duration
}

type Kafka struct {
	Enabled bool

	Brokers []string

	RuntimeEventsTopic string

	RuntimeDLQTopic string

	ConsumerGroup string

	ClientID string

	ProcessMaxAttempts int

	DedupeRetention time.Duration
}

type Governance struct {
	MasterKey string
}

type Verification struct {
	Pepper string

	CodeTTL time.Duration

	Cooldown time.Duration

	SendWindow time.Duration

	MaxSendsPerWindow int64

	MaxVerifyAttempts int64

	SendRecordTTL time.Duration
}

type Config struct {
	Port string

	MySQL MySQL

	Redis Redis

	JWT JWT

	Email Email

	Verification Verification

	Knowledge Knowledge

	DurableRuntime DurableRuntime

	Kafka Kafka

	Governance Governance

	RefreshCookieName string

	CookieSecure bool

	RuntimeBaseURL string

	RuntimeInternalToken string

	RuntimeTimeout time.Duration

	MCPDemoEndpoint string

	AllowedOrigins []string

	TaskRateLimit int
}

func Load() (Config, error) {
	loadLocalEnvironment()

	accessMin, err := positiveInt(
		"JWT_ACCESS_TTL_MINUTES",
		30,
	)

	if err != nil {
		return Config{},
			err
	}

	refreshDays, err := positiveInt(
		"JWT_REFRESH_TTL_DAYS",
		3,
	)

	if err != nil {
		return Config{},
			err
	}

	runtimeSeconds, err := positiveInt(
		"RUNTIME_TIMEOUT_SECONDS",
		30,
	)

	if err != nil {
		return Config{},
			err
	}

	redisDB, err := nonNegativeInt(
		"REDIS_DB",
		0,
	)

	if err != nil {
		return Config{},
			err
	}

	rateLimit, err := positiveInt(
		"TASK_RATE_LIMIT_PER_MINUTE",
		30,
	)

	if err != nil {
		return Config{},
			err
	}

	knowledgeMaxUploadMB, err := positiveInt(
		"KNOWLEDGE_MAX_UPLOAD_MB",
		20,
	)

	if err != nil {
		return Config{},
			err
	}

	durableEnabled, err := strconv.ParseBool(env("DURABLE_RUNTIME_ENABLED", "true"))
	if err != nil {
		return Config{}, errors.New("DURABLE_RUNTIME_ENABLED must be true or false")
	}
	durableDispatcherLeaseSeconds, err := positiveInt("DURABLE_RUNTIME_DISPATCHER_LEASE_SECONDS", 5)
	if err != nil {
		return Config{}, err
	}
	durableExecutionLeaseSeconds, err := positiveInt("DURABLE_RUNTIME_EXECUTION_LEASE_SECONDS", 20)
	if err != nil {
		return Config{}, err
	}
	durablePollMS, err := positiveInt("DURABLE_RUNTIME_POLL_MS", 300)
	if err != nil {
		return Config{}, err
	}
	durableLeaseSeconds, err := positiveInt("DURABLE_RUNTIME_LEASE_SECONDS", 15)
	if err != nil {
		return Config{}, err
	}
	durableWorkerStaleSeconds, err := positiveInt("DURABLE_RUNTIME_WORKER_STALE_SECONDS", 20)
	if err != nil {
		return Config{}, err
	}
	durableAcceptanceSeconds, err := positiveInt("DURABLE_RUNTIME_ACCEPTANCE_TIMEOUT_SECONDS", 5)
	if err != nil {
		return Config{}, err
	}
	durableRetryMS, err := positiveInt("DURABLE_RUNTIME_RETRY_BACKOFF_MS", 500)
	if err != nil {
		return Config{}, err
	}
	durableDeadlineSeconds, err := positiveInt("DURABLE_RUNTIME_JOB_DEADLINE_SECONDS", 120)
	if err != nil {
		return Config{}, err
	}
	durableMaxAttempts, err := positiveInt("DURABLE_RUNTIME_MAX_ATTEMPTS", 3)
	if err != nil {
		return Config{}, err
	}
	durableMaxQueue, err := positiveInt("DURABLE_RUNTIME_MAX_QUEUE_DEPTH", 500)
	if err != nil {
		return Config{}, err
	}
	durableCircuitThreshold, err := positiveInt("DURABLE_RUNTIME_CIRCUIT_FAILURE_THRESHOLD", 3)
	if err != nil {
		return Config{}, err
	}
	durableCircuitOpenSeconds, err := positiveInt("DURABLE_RUNTIME_CIRCUIT_OPEN_SECONDS", 20)
	if err != nil {
		return Config{}, err
	}

	kafkaEnabled, err := strconv.ParseBool(env("KAFKA_ENABLED", "false"))
	if err != nil {
		return Config{}, errors.New("KAFKA_ENABLED must be true or false")
	}
	kafkaProcessMaxAttempts, err := positiveInt("KAFKA_PROCESS_MAX_ATTEMPTS", 10)
	if err != nil {
		return Config{}, err
	}
	kafkaDedupeRetentionDays, err := positiveInt("KAFKA_DEDUPE_RETENTION_DAYS", 30)
	if err != nil {
		return Config{}, err
	}

	verificationTTLMinutes, err := positiveInt(
		"VERIFICATION_CODE_TTL_MINUTES",
		5,
	)

	if err != nil {
		return Config{},
			err
	}

	verificationCooldownSeconds, err := positiveInt(
		"VERIFICATION_COOLDOWN_SECONDS",
		60,
	)

	if err != nil {
		return Config{},
			err
	}

	verificationWindowMinutes, err := positiveInt(
		"VERIFICATION_SEND_WINDOW_MINUTES",
		60,
	)

	if err != nil {
		return Config{},
			err
	}

	maxSendsPerWindow, err := positiveInt(
		"VERIFICATION_MAX_SENDS_PER_WINDOW",
		10,
	)

	if err != nil {
		return Config{},
			err
	}

	maxVerifyAttempts, err := positiveInt(
		"VERIFICATION_MAX_VERIFY_ATTEMPTS",
		5,
	)

	if err != nil {
		return Config{},
			err
	}

	sendRecordSeconds, err := positiveInt(
		"VERIFICATION_SEND_RECORD_SECONDS",
		60,
	)

	if err != nil {
		return Config{},
			err
	}

	secure, err := strconv.ParseBool(
		env(
			"AUTH_COOKIE_SECURE",
			"false",
		),
	)

	if err != nil {
		return Config{},
			errors.New(
				"AUTH_COOKIE_SECURE must be true or false",
			)
	}

	emailProvider := strings.ToLower(
		env(
			"EMAIL_PROVIDER",
			"console",
		),
	)

	cfg := Config{
		Port: env(
			"BUSINESS_PORT",
			"8086",
		),

		MySQL: MySQL{
			Host: env(
				"MYSQL_HOST",
				"127.0.0.1",
			),

			Port: env(
				"MYSQL_PORT",
				"3310",
			),

			Database: os.Getenv(
				"MYSQL_DATABASE",
			),

			User: os.Getenv(
				"MYSQL_USER",
			),

			Password: os.Getenv(
				"MYSQL_PASSWORD",
			),
		},

		Redis: Redis{
			Addr: env(
				"REDIS_ADDR",
				"127.0.0.1:6382",
			),

			Password: os.Getenv(
				"REDIS_PASSWORD",
			),

			DB: redisDB,
		},

		JWT: JWT{
			Secret: os.Getenv(
				"JWT_SECRET",
			),

			Issuer: env(
				"JWT_ISSUER",
				"agentmesh-control-plane",
			),

			AccessTTL: time.Duration(
				accessMin,
			) * time.Minute,

			RefreshTTL: time.Duration(
				refreshDays,
			) * 24 * time.Hour,
		},

		Email: Email{
			Provider: emailProvider,

			Address: strings.TrimSpace(
				os.Getenv(
					"EMAIL_ADDRESS",
				),
			),

			AuthCode: strings.TrimSpace(
				os.Getenv(
					"EMAIL_AUTH_CODE",
				),
			),

			AppName: env(
				"EMAIL_APP_NAME",
				"AgentMesh",
			),
		},

		Verification: Verification{
			Pepper: strings.TrimSpace(
				os.Getenv(
					"VERIFICATION_PEPPER",
				),
			),

			CodeTTL: time.Duration(
				verificationTTLMinutes,
			) * time.Minute,

			Cooldown: time.Duration(
				verificationCooldownSeconds,
			) * time.Second,

			SendWindow: time.Duration(
				verificationWindowMinutes,
			) * time.Minute,

			MaxSendsPerWindow: int64(
				maxSendsPerWindow,
			),

			MaxVerifyAttempts: int64(
				maxVerifyAttempts,
			),

			SendRecordTTL: time.Duration(
				sendRecordSeconds,
			) * time.Second,
		},

		Knowledge: Knowledge{
			StorageRoot: env(
				"KNOWLEDGE_STORAGE_ROOT",
				"./data/knowledge",
			),

			MaxUploadBytes: int64(
				knowledgeMaxUploadMB,
			) * 1024 * 1024,
		},

		DurableRuntime: DurableRuntime{
			Enabled:                 durableEnabled,
			ControlPlaneBaseURL:     env("CONTROL_PLANE_INTERNAL_BASE_URL", "http://127.0.0.1:8086"),
			DispatcherID:            env("DURABLE_RUNTIME_DISPATCHER_ID", "dispatcher-local-1"),
			DispatcherLeaseDuration: time.Duration(durableDispatcherLeaseSeconds) * time.Second,
			PollInterval:            time.Duration(durablePollMS) * time.Millisecond,
			LeaseDuration:           time.Duration(durableLeaseSeconds) * time.Second,
			ExecutionLeaseDuration:  time.Duration(durableExecutionLeaseSeconds) * time.Second,
			WorkerStaleAfter:        time.Duration(durableWorkerStaleSeconds) * time.Second,
			AcceptanceTimeout:       time.Duration(durableAcceptanceSeconds) * time.Second,
			RetryBackoff:            time.Duration(durableRetryMS) * time.Millisecond,
			JobDeadline:             time.Duration(durableDeadlineSeconds) * time.Second,
			MaxAttempts:             durableMaxAttempts,
			MaxQueueDepth:           durableMaxQueue,
			CircuitFailureThreshold: durableCircuitThreshold,
			CircuitOpenFor:          time.Duration(durableCircuitOpenSeconds) * time.Second,
		},

		Kafka: Kafka{
			Enabled:            kafkaEnabled,
			Brokers:            splitCSV(env("KAFKA_BROKERS", "127.0.0.1:29092")),
			RuntimeEventsTopic: env("KAFKA_RUNTIME_EVENTS_TOPIC", "agentmesh.runtime.events"),
			RuntimeDLQTopic:    env("KAFKA_RUNTIME_DLQ_TOPIC", "agentmesh.runtime.events.dlq"),
			ConsumerGroup:      env("KAFKA_RUNTIME_CONSUMER_GROUP", "agentmesh-control-plane-runtime-v1"),
			ClientID:           env("KAFKA_CLIENT_ID", "agentmesh-control-plane"),
			ProcessMaxAttempts: kafkaProcessMaxAttempts,
			DedupeRetention:    time.Duration(kafkaDedupeRetentionDays) * 24 * time.Hour,
		},

		RefreshCookieName: env(
			"AUTH_REFRESH_COOKIE_NAME",
			"refresh_token",
		),

		CookieSecure: secure,

		RuntimeBaseURL: env(
			"RUNTIME_BASE_URL",
			"http://127.0.0.1:9572",
		),

		RuntimeInternalToken: os.Getenv(
			"RUNTIME_INTERNAL_TOKEN",
		),

		RuntimeTimeout: time.Duration(
			runtimeSeconds,
		) * time.Second,

		MCPDemoEndpoint: env(
			"MCP_DEMO_ENDPOINT",
			"http://127.0.0.1:9583/mcp",
		),

		AllowedOrigins: splitCSV(
			env(
				"ALLOWED_ORIGINS",
				"http://localhost:5173,http://127.0.0.1:5173",
			),
		),

		TaskRateLimit: rateLimit,

		Governance: Governance{
			MasterKey: strings.TrimSpace(os.Getenv("GOVERNANCE_MASTER_KEY")),
		},
	}

	if cfg.Governance.MasterKey == "" {
		cfg.Governance.MasterKey = cfg.JWT.Secret
	}

	if cfg.MySQL.Database == "" ||
		cfg.MySQL.User == "" ||
		cfg.MySQL.Password == "" {
		return Config{},
			errors.New(
				"MYSQL_DATABASE/MYSQL_USER/MYSQL_PASSWORD are required",
			)
	}

	if len(
		cfg.JWT.Secret,
	) < 32 {
		return Config{},
			errors.New(
				"JWT_SECRET must be at least 32 characters",
			)
	}

	if len(
		cfg.Governance.MasterKey,
	) < 32 {
		return Config{},
			errors.New(
				"GOVERNANCE_MASTER_KEY must be at least 32 characters",
			)
	}

	if len(
		cfg.RuntimeInternalToken,
	) < 16 {
		return Config{},
			errors.New(
				"RUNTIME_INTERNAL_TOKEN must be at least 16 characters",
			)
	}

	if len(
		cfg.Verification.Pepper,
	) < 16 {
		return Config{},
			errors.New(
				"VERIFICATION_PEPPER must be at least 16 characters",
			)
	}

	switch cfg.Email.Provider {
	case "console":
		// Local development only.

	case "qq",
		"163",
		"netease",
		"126":
		if cfg.Email.Address == "" ||
			cfg.Email.AuthCode == "" {
			return Config{},
				errors.New(
					"EMAIL_ADDRESS/EMAIL_AUTH_CODE are required for SMTP email provider",
				)
		}

	default:
		return Config{},
			errors.New(
				"EMAIL_PROVIDER must be console, qq, 163, netease, or 126",
			)
	}

	return cfg,
		nil
}

func loadLocalEnvironment() {
	if explicit := strings.TrimSpace(os.Getenv("AGENTMESH_ENV_FILE")); explicit != "" {
		_ = godotenv.Load(explicit)
		return
	}

	workingDirectory, err := os.Getwd()
	if err != nil {
		return
	}

	for directory := workingDirectory; ; directory = filepath.Dir(directory) {
		for _, name := range []string{".env.local", ".env"} {
			candidate := filepath.Join(directory, name)
			if info, statErr := os.Stat(candidate); statErr == nil && !info.IsDir() {
				// godotenv.Load intentionally does not overwrite variables that are
				// already present in the real process environment. Local files are
				// therefore developer defaults, never production overrides.
				_ = godotenv.Load(candidate)
				return
			}
		}

		parent := filepath.Dir(directory)
		if parent == directory {
			return
		}
	}
}

func env(
	key string,
	fallback string,
) string {
	if value := strings.TrimSpace(
		os.Getenv(
			key,
		),
	); value != "" {
		return value
	}

	return fallback
}

func positiveInt(
	key string,
	fallback int,
) (int, error) {
	value, err := strconv.Atoi(
		env(
			key,
			strconv.Itoa(
				fallback,
			),
		),
	)

	if err != nil ||
		value <= 0 {
		return 0,
			errors.New(
				key + " must be positive",
			)
	}

	return value,
		nil
}

func nonNegativeInt(
	key string,
	fallback int,
) (int, error) {
	value, err := strconv.Atoi(
		env(
			key,
			strconv.Itoa(
				fallback,
			),
		),
	)

	if err != nil ||
		value < 0 {
		return 0,
			errors.New(
				key + " must be non-negative",
			)
	}

	return value,
		nil
}

func splitCSV(
	value string,
) []string {
	parts := strings.Split(
		value,
		",",
	)

	output := make(
		[]string,
		0,
		len(
			parts,
		),
	)

	for _, item := range parts {
		item = strings.TrimSpace(
			item,
		)

		if item != "" {
			output = append(
				output,
				item,
			)
		}
	}

	return output
}
