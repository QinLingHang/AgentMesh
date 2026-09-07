package router_test

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/config"
	dbschema "example.com/agentmesh-control-plane/internal/db"
	mysql "github.com/go-sql-driver/mysql"
)

const p31InternalToken = "p31-test-only-internal-token"

// A distinct test package cannot reuse service's unexported P2 test helper.
// Keep this helper test-only and use exactly the same production DDL/migrations.
func p31Database(t *testing.T) (*sql.DB, string) {
	t.Helper()
	dsn := os.Getenv("P3_TEST_MYSQL_DSN")
	if dsn == "" {
		t.Skip("set P3_TEST_MYSQL_DSN to run real MySQL/HTTP P3.1 acceptance")
	}
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		t.Fatal(err)
	}
	cfg.DBName = ""
	cfg.ParseTime = true
	admin, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close() })
	name := fmt.Sprintf("agentmesh_p31_test_%d", time.Now().UnixNano())
	if _, err = admin.Exec("CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec("DROP DATABASE `" + name + "`"); err != nil {
			t.Errorf("test database cleanup: %v", err)
		}
	})
	cfg.DBName = name
	cfg.MultiStatements = true
	database, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { database.Close() })
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "infra", "mysql", "init", "001_schema.sql"))
	if err != nil {
		t.Fatal(err)
	}
	pos := strings.Index(string(raw), "CREATE TABLE")
	if pos < 0 {
		t.Fatal("base schema missing CREATE TABLE")
	}
	if _, err = database.Exec(string(raw)[pos:]); err != nil {
		t.Fatal(err)
	}
	host, port, err := net.SplitHostPort(cfg.Addr)
	if err != nil {
		t.Fatal(err)
	}
	migrated, err := dbschema.Open(config.MySQL{Host: host, Port: port, User: cfg.User, Password: cfg.Passwd, Database: name})
	if err != nil {
		t.Fatal(err)
	}
	if err = dbschema.Migrate(context.Background(), migrated); err != nil {
		migrated.Close()
		t.Fatal(err)
	}
	migrated.Close()
	// Existing-database upgrade: users and projects already exist before P3.1.
	if _, err = database.Exec("INSERT INTO users(id,email,password_hash,display_name) VALUES(1,'p31-a@example.test','fixture','A'),(2,'p31-b@example.test','fixture','B')"); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err = dbschema.EnsureMemorySchema(context.Background(), database); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("isolated MySQL schema: %s (upgrade and idempotent migration applied)", name)
	return database, cfg.FormatDSN()
}

func p31PythonKnowledgeHost(t *testing.T) string {
	t.Helper()
	executable := os.Getenv("P3_TEST_PYTHON")
	if executable == "" {
		executable = "python"
	}
	script, err := filepath.Abs(filepath.Join("..", "..", "..", "runtime-python", "tests", "p3_1_knowledge_http_fixture.py"))
	if err != nil {
		t.Fatal(err)
	}
	command := exec.Command(executable, "-u", script)
	command.Dir = filepath.Dir(filepath.Dir(script))
	// Override test settings without inheriting external model credentials or
	// triggering a real provider; this helper never constructs a model engine.
	command.Env = append(os.Environ(), "INTERNAL_TOKEN="+p31InternalToken, "MODEL_PROVIDER=mock", "RAG_BACKEND=inmemory", "EMBEDDING_BACKEND=hash", "RERANKER_BACKEND=heuristic", "PYTHONDONTWRITEBYTECODE=1")
	stderr, err := os.CreateTemp(t.TempDir(), "python-*.log")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { stderr.Close() })
	command.Stderr = stderr
	stdout, err := command.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = command.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = command.Process.Kill(); _ = command.Wait(); _ = stdout.Close() })
	ready := make(chan string, 1)
	go func() {
		reader := bufio.NewReader(stdout)
		line, _ := reader.ReadString('\n')
		ready <- line
		_, _ = io.Copy(io.Discard, reader)
	}()
	var line string
	select {
	case line = <-ready:
	case <-time.After(25 * time.Second):
		t.Fatal("Python knowledge fixture startup timeout")
	}
	var handshake struct {
		Port int `json:"port"`
	}
	if err = json.Unmarshal([]byte(line), &handshake); err != nil || handshake.Port <= 0 {
		raw, _ := os.ReadFile(stderr.Name())
		t.Fatalf("Python fixture startup: %q; %s", line, raw)
	}
	base := fmt.Sprintf("http://127.0.0.1:%d", handshake.Port)
	client := http.Client{Timeout: time.Second}
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(30 * time.Millisecond) {
		res, err := client.Get(base + "/health")
		if err == nil {
			res.Body.Close()
			if res.StatusCode == 200 {
				return base
			}
		}
	}
	t.Fatal("Python knowledge fixture never became healthy")
	return ""
}
