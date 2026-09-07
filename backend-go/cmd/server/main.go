package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os/signal"
	"syscall"
	"time"

	"example.com/agentmesh-control-plane/internal/cache"
	"example.com/agentmesh-control-plane/internal/config"
	"example.com/agentmesh-control-plane/internal/db"
	"example.com/agentmesh-control-plane/internal/handler"
	"example.com/agentmesh-control-plane/internal/repository"
	"example.com/agentmesh-control-plane/internal/router"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"example.com/agentmesh-control-plane/internal/security"
	"example.com/agentmesh-control-plane/internal/service"
	"example.com/agentmesh-control-plane/internal/storage"
	"example.com/agentmesh-control-plane/internal/verification"
)

func main() {
	cfg, err := config.Load()

	if err != nil {
		log.Fatal(
			err,
		)
	}

	sqlDB, err := db.Open(
		cfg.MySQL,
	)

	if err != nil {
		log.Fatal(
			err,
		)
	}

	defer sqlDB.Close()

	schemaCtx, schemaCancel := context.WithTimeout(
		context.Background(),
		60*time.Second,
	)
	if err = db.Migrate(schemaCtx, sqlDB); err != nil {
		schemaCancel()
		log.Fatal(err)
	}
	schemaCancel()

	rdb, err := cache.Open(
		cfg.Redis,
	)

	if err != nil {
		log.Fatal(
			err,
		)
	}

	defer rdb.Close()

	store := repository.NewMySQL(
		sqlDB,
	)

	knowledgeStore, err :=
		storage.NewLocalObjectStore(
			cfg.Knowledge.StorageRoot,
		)

	if err != nil {
		log.Fatal(err)
	}

	jwt := security.NewJWTManager(
		cfg.JWT.Secret,
		cfg.JWT.Issuer,
		cfg.JWT.AccessTTL,
	)

	runtime := runtimeclient.NewClient(
		cfg.RuntimeBaseURL,
		cfg.RuntimeInternalToken,
		cfg.RuntimeTimeout,
	)

	knowledgeS := service.NewKnowledgeService(
		store,
		knowledgeStore,
		cfg.Knowledge.MaxUploadBytes,
		runtime,
	)

	attachmentS := service.NewAttachmentService(
		store,
		knowledgeStore,
		cfg.Knowledge.MaxUploadBytes,
	)

	emailSender, err := buildEmailSender(
		cfg.Email,
	)

	if err != nil {
		log.Fatal(
			err,
		)
	}

	verificationService, err := verification.NewService(
		verification.NewRedisStore(
			rdb,
		),
		emailSender,
		verification.Config{
			TTL: cfg.Verification.CodeTTL,

			Cooldown: cfg.Verification.Cooldown,

			SendWindow: cfg.Verification.SendWindow,

			MaxSendsPerWindow: cfg.Verification.MaxSendsPerWindow,

			MaxVerifyAttempts: cfg.Verification.MaxVerifyAttempts,

			SendRecordTTL: cfg.Verification.SendRecordTTL,

			Pepper: cfg.Verification.Pepper,
		},
	)

	if err != nil {
		log.Fatal(
			err,
		)
	}

	authS := service.NewAuthService(
		store,
		store,
		jwt,
		cfg.JWT.RefreshTTL,
	)

	verificationAuthS := service.NewVerificationAuthService(
		store,
		store,
		authS,
		verificationService,
	)

	convS := service.NewConversationService(
		store,
		store,
	)

	convS.SetAttachmentService(attachmentS)

	projectS := service.NewProjectService(
		store,
		knowledgeS,
	)

	projectRuntimeS := service.NewProjectRuntimeService(
		store,
	)

	memoryS := service.NewMemoryService(
		store,
	)

	agentS := service.NewAgentService(
		store,
	)

	toolS := service.NewToolService(
		store,
	)

	mcpS := service.NewMCPServerService(
		store,
		runtime,
		cfg.MCPDemoEndpoint,
	)

	governanceS, err := service.NewGovernanceService(store, cfg.Governance.MasterKey)
	if err != nil {
		log.Fatal(err)
	}

	knowledgeS.SetGovernanceService(governanceS)

	taskS := service.NewTaskService(
		store,
		store,
		store,
		runtime,
		store,
		store,
		projectRuntimeS,
	)

	taskS.SetGovernanceService(governanceS)
	taskS.SetAttachmentService(attachmentS)

	durableRuntimeS := service.NewDurableRuntimeService(
		store,
		taskS,
		runtime,
		service.DurableRuntimeConfig{
			Enabled:                 cfg.DurableRuntime.Enabled,
			ControlPlaneBaseURL:     cfg.DurableRuntime.ControlPlaneBaseURL,
			DispatcherID:            cfg.DurableRuntime.DispatcherID,
			DispatcherLeaseDuration: cfg.DurableRuntime.DispatcherLeaseDuration,
			PollInterval:            cfg.DurableRuntime.PollInterval,
			LeaseDuration:           cfg.DurableRuntime.LeaseDuration,
			ExecutionLeaseDuration:  cfg.DurableRuntime.ExecutionLeaseDuration,
			WorkerStaleAfter:        cfg.DurableRuntime.WorkerStaleAfter,
			AcceptanceTimeout:       cfg.DurableRuntime.AcceptanceTimeout,
			RetryBackoff:            cfg.DurableRuntime.RetryBackoff,
			JobDeadline:             cfg.DurableRuntime.JobDeadline,
			MaxAttempts:             cfg.DurableRuntime.MaxAttempts,
			MaxQueueDepth:           cfg.DurableRuntime.MaxQueueDepth,
			CircuitFailureThreshold: cfg.DurableRuntime.CircuitFailureThreshold,
			CircuitOpenFor:          cfg.DurableRuntime.CircuitOpenFor,
		},
	)

	authH := handler.NewAuthHandler(
		authS,
		cfg.RefreshCookieName,
		cfg.CookieSecure,
		cfg.JWT.RefreshTTL,
	)

	verificationAuthH := handler.NewVerificationAuthHandler(
		verificationAuthS,
		cfg.RefreshCookieName,
		cfg.CookieSecure,
		cfg.JWT.RefreshTTL,
	)

	convH := handler.NewConversationHandler(
		convS,
	)

	projectH := handler.NewProjectHandler(
		projectS,
	)

	projectRuntimeH := handler.NewProjectRuntimeHandler(
		projectRuntimeS,
	)

	memoryH := handler.NewMemoryHandler(
		memoryS,
	)

	knowledgeH := handler.NewKnowledgeHandler(
		knowledgeS,
		cfg.Knowledge.MaxUploadBytes,
	)

	attachmentH := handler.NewAttachmentHandler(attachmentS)

	agentH := handler.NewAgentHandler(
		agentS,
	)

	toolH := handler.NewToolHandler(
		toolS,
	)

	mcpH := handler.NewMCPServerHandler(
		mcpS,
	)

	governanceH := handler.NewGovernanceHandler(governanceS)

	taskH := handler.NewTaskHandler(
		taskS,
	)

	durableRuntimeH := handler.NewDurableRuntimeHandler(
		durableRuntimeS,
	)

	r := router.New(
		router.Dependencies{
			AuthHandler: authH,

			VerificationAuthHandler: verificationAuthH,

			ConversationHandler: convH,

			ProjectHandler: projectH,

			ProjectRuntimeHandler: projectRuntimeH,

			MemoryHandler: memoryH,

			KnowledgeHandler: knowledgeH,

			AttachmentHandler: attachmentH,

			AgentHandler: agentH,

			TaskHandler: taskH,

			DurableRuntimeHandler: durableRuntimeH,

			ToolHandler: toolH,

			MCPServerHandler: mcpH,

			GovernanceHandler: governanceH,

			JWT: jwt,

			DB: sqlDB,

			Redis: rdb,

			AllowedOrigins: cfg.AllowedOrigins,

			TaskRateLimit: cfg.TaskRateLimit,

			InternalToken: cfg.RuntimeInternalToken,
		},
	)

	rootCtx, stopSignal := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stopSignal()
	durableRuntimeS.Start(rootCtx)
	defer durableRuntimeS.Stop()

	server := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
	}

	log.Printf(
		"AgentMesh Go control plane listening on :%s",
		cfg.Port,
	)

	serverErr := make(chan error, 1)
	go func() {
		err := server.ListenAndServe()
		if err != nil && err != http.ErrServerClosed {
			serverErr <- err
			return
		}
		serverErr <- nil
	}()

	select {
	case <-rootCtx.Done():
		log.Printf("shutdown signal received; draining control plane")
	case err := <-serverErr:
		if err != nil {
			log.Printf("control plane server failed: %v", err)
		}
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer shutdownCancel()
	durableRuntimeS.Stop()
	if err := server.Shutdown(shutdownCtx); err != nil {
		log.Printf("control plane graceful shutdown failed: %v", err)
	}
}

func buildEmailSender(
	cfg config.Email,
) (verification.EmailSender, error) {
	switch cfg.Provider {
	case "console":
		log.Printf(
			"AgentMesh email provider: console (development only)",
		)

		return verification.NewConsoleEmailSender(),
			nil

	case "qq",
		"163",
		"netease",
		"126":
		smtpConfig, err := verification.CommonSMTPConfig(
			cfg.Provider,
			cfg.Address,
			cfg.AuthCode,
			cfg.AppName,
		)

		if err != nil {
			return nil,
				err
		}

		log.Printf(
			"AgentMesh email provider: %s",
			cfg.Provider,
		)

		return verification.NewSMTPEmailSender(
			smtpConfig,
		), nil

	default:
		return nil,
			fmt.Errorf(
				"unsupported email provider: %s",
				cfg.Provider,
			)
	}
}
