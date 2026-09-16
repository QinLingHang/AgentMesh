package router

import (
	"context"
	"database/sql"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

func registerHealthRoutes(r *gin.Engine, database *sql.DB, redisClient *redis.Client, eventPlaneStatus func() map[string]any) {
	// Backwards-compatible shallow endpoint used by existing local scripts.
	r.GET("/health", func(c *gin.Context) {
		payload := gin.H{"status": "ok", "service": "agentmesh-go"}
		if eventPlaneStatus != nil {
			payload["eventPlane"] = eventPlaneStatus()
		}
		c.JSON(http.StatusOK, payload)
	})

	// Liveness answers only whether this process is alive. It deliberately does
	// not depend on external services so an orchestrator does not restart a
	// healthy process during a transient database outage.
	r.GET("/livez", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "alive", "service": "agentmesh-go"})
	})

	// Readiness is the traffic-admission boundary. The control plane requires
	// both MySQL and Redis before it should receive user traffic.
	r.GET("/readyz", func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		defer cancel()

		checks := gin.H{}
		ready := true

		if database == nil {
			checks["mysql"] = "unavailable"
			ready = false
		} else if err := database.PingContext(ctx); err != nil {
			checks["mysql"] = "unavailable"
			ready = false
		} else {
			checks["mysql"] = "ok"
		}

		if redisClient == nil {
			checks["redis"] = "unavailable"
			ready = false
		} else if err := redisClient.Ping(ctx).Err(); err != nil {
			checks["redis"] = "unavailable"
			ready = false
		} else {
			checks["redis"] = "ok"
		}

		status := http.StatusOK
		state := "ready"
		if !ready {
			status = http.StatusServiceUnavailable
			state = "not_ready"
		}

		c.JSON(status, gin.H{
			"status":  state,
			"service": "agentmesh-go",
			"checks":  checks,
		})
	})
}
