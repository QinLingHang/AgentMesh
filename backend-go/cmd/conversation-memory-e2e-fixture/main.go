package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	mysql "github.com/go-sql-driver/mysql"
)

type seedResult struct {
	UserID         int64  `json:"userId"`
	ConversationID int64  `json:"conversationId"`
	Count          int    `json:"count"`
	FirstMarker    string `json:"firstMarker"`
	LastMarker     string `json:"lastMarker"`
}

func main() {
	flag.Parse()
	if flag.NArg() < 1 {
		log.Fatal("usage: conversation-memory-e2e-fixture seed-history [flags]")
	}
	switch flag.Arg(0) {
	case "seed-history":
		seedHistory(flag.Args()[1:])
	default:
		log.Fatalf("unknown action %q", flag.Arg(0))
	}
}

func adminConfig() *mysql.Config {
	dsn := strings.TrimSpace(os.Getenv("QA_TEST_MYSQL_DSN"))
	if dsn == "" {
		log.Fatal("QA_TEST_MYSQL_DSN is required for Conversation Reliability memory E2E fixture")
	}
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		log.Fatal(err)
	}
	cfg.ParseTime = true
	return cfg
}

func openFixtureDatabase(name string) *sql.DB {
	if !strings.HasPrefix(name, "agentmesh_browser_e2e_") {
		log.Fatal("refusing to seed outside an isolated browser/V4.1 QA database")
	}
	cfg := adminConfig()
	cfg.DBName = name
	database, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		log.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := database.PingContext(ctx); err != nil {
		database.Close()
		log.Fatal(err)
	}
	return database
}

func seedHistory(args []string) {
	fs := flag.NewFlagSet("seed-history", flag.ExitOnError)
	databaseName := fs.String("database", "", "isolated fixture database")
	email := fs.String("email", "", "registered fixture user email")
	count := fs.Int("count", 125, "number of durable messages")
	markerPrefix := fs.String("marker-prefix", "CONVERSATION_HISTORY", "durable message marker prefix")
	_ = fs.Parse(args)
	if *databaseName == "" || strings.TrimSpace(*email) == "" || *count < 20 || *count > 500 {
		log.Fatal("seed-history requires --database --email and --count between 20 and 500")
	}

	database := openFixtureDatabase(*databaseName)
	defer database.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	var uid int64
	if err := database.QueryRowContext(ctx, "SELECT id FROM users WHERE email=? LIMIT 1", strings.TrimSpace(*email)).Scan(&uid); err != nil {
		log.Fatal(err)
	}
	result, err := database.ExecContext(
		ctx,
		"INSERT INTO conversations(user_id,title) VALUES(?,?)",
		uid,
		fmt.Sprintf("Conversation Reliability Durable History %d", time.Now().UnixNano()),
	)
	if err != nil {
		log.Fatal(err)
	}
	conversationID, err := result.LastInsertId()
	if err != nil {
		log.Fatal(err)
	}

	firstMarker := ""
	lastMarker := ""
	for index := 1; index <= *count; index++ {
		role := "user"
		if index%2 == 0 {
			role = "assistant"
		}
		marker := fmt.Sprintf("%s_%03d", strings.TrimSpace(*markerPrefix), index)
		if index == 1 {
			firstMarker = marker
		}
		if index == *count {
			lastMarker = marker
		}
		content := fmt.Sprintf(
			"%s durable conversation message. This sentence intentionally carries enough stable text for compaction threshold coverage while remaining safe and deterministic.",
			marker,
		)
		requestID := fmt.Sprintf("conversation-reliability-memory-e2e-%03d", (index+1)/2)
		if _, err := database.ExecContext(
			ctx,
			"INSERT INTO messages(conversation_id,role,content,status,request_id,metadata_json) VALUES(?,?,?,?,?,?)",
			conversationID, role, content, "COMPLETED", requestID, "{}",
		); err != nil {
			log.Fatal(err)
		}
	}

	if err := json.NewEncoder(os.Stdout).Encode(seedResult{
		UserID:         uid,
		ConversationID: conversationID,
		Count:          *count,
		FirstMarker:    firstMarker,
		LastMarker:     lastMarker,
	}); err != nil {
		log.Fatal(err)
	}
}
