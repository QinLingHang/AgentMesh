package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	dbschema "example.com/agentmesh-control-plane/internal/db"
	"example.com/agentmesh-control-plane/internal/security"
	mysql "github.com/go-sql-driver/mysql"
)

type fixture struct {
	Database       string `json:"database"`
	Host           string `json:"host"`
	Port           string `json:"port"`
	User           string `json:"user"`
	Password       string `json:"password"`
	MemberEmail    string `json:"memberEmail"`
	MemberPassword string `json:"memberPassword"`
}

func main() {
	flag.Parse()
	if flag.NArg() < 1 {
		log.Fatal("usage: p12-e2e-fixture <prepare|verify|cleanup> [flags]")
	}

	switch flag.Arg(0) {
	case "prepare":
		prepare()
	case "verify":
		verify(flag.Args()[1:])
	case "cleanup":
		cleanup(flag.Args()[1:])
	default:
		log.Fatalf("unknown action %q", flag.Arg(0))
	}
}

func adminConfig() *mysql.Config {
	dsn := strings.TrimSpace(os.Getenv("P2_TEST_MYSQL_DSN"))
	if dsn == "" {
		log.Fatal("P2_TEST_MYSQL_DSN is required for the real P12 browser QA fixture")
	}
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		log.Fatal(err)
	}
	cfg.DBName = ""
	cfg.ParseTime = true
	cfg.MultiStatements = true
	return cfg
}

func openAdmin() (*sql.DB, *mysql.Config) {
	cfg := adminConfig()
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
	return database, cfg
}

func prepare() {
	admin, cfg := openAdmin()
	defer admin.Close()

	name := fmt.Sprintf("agentmesh_p12_browser_%d", time.Now().UnixNano())
	if _, err := admin.Exec("CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4"); err != nil {
		log.Fatal(err)
	}
	cleanupOnError := true
	defer func() {
		if cleanupOnError {
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
		}
	}()

	dbCfg := *cfg
	dbCfg.DBName = name
	database, err := sql.Open("mysql", dbCfg.FormatDSN())
	if err != nil {
		log.Fatal(err)
	}
	defer database.Close()

	schemaPath := filepath.Join("..", "infra", "mysql", "init", "001_schema.sql")
	raw, err := os.ReadFile(schemaPath)
	if err != nil {
		log.Fatal(err)
	}
	schema := string(raw)
	pos := strings.Index(schema, "CREATE TABLE")
	if pos < 0 {
		log.Fatal("base schema has no CREATE TABLE statement")
	}
	if _, err := database.Exec(schema[pos:]); err != nil {
		log.Fatal(err)
	}
	if err := dbschema.Migrate(context.Background(), database); err != nil {
		log.Fatal(err)
	}

	memberEmail := fmt.Sprintf("p12-browser-member-%d@example.test", time.Now().UnixNano())
	memberPassword := "P12MemberPass!123"
	hash, err := security.HashPassword(memberPassword)
	if err != nil {
		log.Fatal(err)
	}
	if _, err := database.Exec(
		"INSERT INTO users(email,password_hash,display_name,status) VALUES(?,?,?,'ACTIVE')",
		memberEmail,
		hash,
		"P12 Browser Member",
	); err != nil {
		log.Fatal(err)
	}

	host, port := splitAddr(cfg.Addr)
	cleanupOnError = false
	encode(fixture{
		Database:       name,
		Host:           host,
		Port:           port,
		User:           cfg.User,
		Password:       cfg.Passwd,
		MemberEmail:    memberEmail,
		MemberPassword: memberPassword,
	})
}

func verify(args []string) {
	fs := flag.NewFlagSet("verify", flag.ExitOnError)
	databaseName := fs.String("database", "", "fixture database")
	orgName := fs.String("organization", "", "organization name")
	projectName := fs.String("project", "", "project name")
	memberEmail := fs.String("member", "", "organization member email")
	_ = fs.Parse(args)
	if *databaseName == "" || *orgName == "" || *projectName == "" || *memberEmail == "" {
		log.Fatal("verify requires --database --organization --project --member")
	}

	admin, cfg := openAdmin()
	admin.Close()
	dbCfg := *cfg
	dbCfg.DBName = *databaseName
	database, err := sql.Open("mysql", dbCfg.FormatDSN())
	if err != nil {
		log.Fatal(err)
	}
	defer database.Close()

	var orgCount, memberCount, bindingCount int
	if err := database.QueryRow("SELECT COUNT(*) FROM organizations WHERE name=?", *orgName).Scan(&orgCount); err != nil {
		log.Fatal(err)
	}
	if err := database.QueryRow(`SELECT COUNT(*) FROM organization_members om JOIN organizations o ON o.id=om.organization_id JOIN users u ON u.id=om.user_id WHERE o.name=? AND u.email=?`, *orgName, *memberEmail).Scan(&memberCount); err != nil {
		log.Fatal(err)
	}
	if err := database.QueryRow(`SELECT COUNT(*) FROM organization_projects op JOIN organizations o ON o.id=op.organization_id JOIN projects p ON p.id=op.project_id WHERE o.name=? AND p.name=?`, *orgName, *projectName).Scan(&bindingCount); err != nil {
		log.Fatal(err)
	}
	if orgCount != 1 || memberCount != 1 || bindingCount != 1 {
		log.Fatalf("organization persistence mismatch: org=%d member=%d binding=%d", orgCount, memberCount, bindingCount)
	}
	encode(map[string]any{"organization": orgCount, "member": memberCount, "binding": bindingCount})
}

func cleanup(args []string) {
	fs := flag.NewFlagSet("cleanup", flag.ExitOnError)
	databaseName := fs.String("database", "", "fixture database")
	_ = fs.Parse(args)
	if *databaseName == "" {
		log.Fatal("cleanup requires --database")
	}
	if !strings.HasPrefix(*databaseName, "agentmesh_p12_browser_") {
		log.Fatal("refusing to drop non-P12 QA database")
	}
	admin, _ := openAdmin()
	defer admin.Close()
	if _, err := admin.Exec("DROP DATABASE IF EXISTS `" + *databaseName + "`"); err != nil {
		log.Fatal(err)
	}
	encode(map[string]any{"dropped": *databaseName})
}

func splitAddr(addr string) (string, string) {
	value := strings.TrimPrefix(addr, "tcp(")
	value = strings.TrimSuffix(value, ")")
	idx := strings.LastIndex(value, ":")
	if idx <= 0 || idx == len(value)-1 {
		log.Fatalf("unsupported MySQL address %q", addr)
	}
	return value[:idx], value[idx+1:]
}

func encode(value any) {
	if err := json.NewEncoder(os.Stdout).Encode(value); err != nil {
		log.Fatal(err)
	}
}
