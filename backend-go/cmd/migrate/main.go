package main

import (
	"context"
	"log"
	"time"

	"example.com/agentmesh-control-plane/internal/config"
	"example.com/agentmesh-control-plane/internal/db"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatal(err)
	}

	database, err := db.Open(cfg.MySQL)
	if err != nil {
		log.Fatal(err)
	}
	defer database.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := db.Migrate(ctx, database); err != nil {
		log.Fatal(err)
	}

	log.Print("AgentMesh database migrations completed")
}
