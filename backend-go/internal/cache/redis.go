package cache

import (
	"context"
	"example.com/agentmesh-control-plane/internal/config"
	"github.com/redis/go-redis/v9"
	"time"
)

func Open(cfg config.Redis) (*redis.Client, error) {
	c := redis.NewClient(&redis.Options{Addr: cfg.Addr, Password: cfg.Password, DB: cfg.DB})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := c.Ping(ctx).Err(); err != nil {
		return nil, err
	}
	return c, nil
}
