package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadLocalEnvironmentFindsNearestEnvLocal(t *testing.T) {
	previous, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}

	root := t.TempDir()
	nested := filepath.Join(root, "backend-go", "internal", "config")

	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(
		filepath.Join(root, "backend-go", ".env.local"),
		[]byte("AGENTMESH_LOCAL_ENV_TEST=loaded\n"),
		0o600,
	); err != nil {
		t.Fatal(err)
	}

	if err := os.Chdir(nested); err != nil {
		t.Fatal(err)
	}

	// 必须在测试函数返回前恢复工作目录。
	// Windows 下如果进程仍停留在 t.TempDir() 内，
	// testing 框架清理临时目录时会因为目录仍被占用而失败。
	defer func() {
		if err := os.Chdir(previous); err != nil {
			t.Errorf("restore working directory: %v", err)
		}
	}()

	t.Setenv("AGENTMESH_LOCAL_ENV_TEST", "")
	if err := os.Unsetenv("AGENTMESH_LOCAL_ENV_TEST"); err != nil {
		t.Fatal(err)
	}

	if err := os.Unsetenv("AGENTMESH_ENV_FILE"); err != nil {
		t.Fatal(err)
	}

	loadLocalEnvironment()

	if got := os.Getenv("AGENTMESH_LOCAL_ENV_TEST"); got != "loaded" {
		t.Fatalf("expected nearest .env.local to load, got %q", got)
	}
}

func TestLoadLocalEnvironmentDoesNotOverrideRealEnvironment(t *testing.T) {
	previous, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}

	root := t.TempDir()

	if err := os.WriteFile(
		filepath.Join(root, ".env.local"),
		[]byte("AGENTMESH_LOCAL_ENV_TEST=file-value\n"),
		0o600,
	); err != nil {
		t.Fatal(err)
	}

	if err := os.Chdir(root); err != nil {
		t.Fatal(err)
	}

	// 与上一个测试一样，在 t.TempDir() cleanup 发生之前
	// 主动恢复到原始工作目录，避免 Windows 目录占用问题。
	defer func() {
		if err := os.Chdir(previous); err != nil {
			t.Errorf("restore working directory: %v", err)
		}
	}()

	t.Setenv("AGENTMESH_LOCAL_ENV_TEST", "process-value")

	if err := os.Unsetenv("AGENTMESH_ENV_FILE"); err != nil {
		t.Fatal(err)
	}

	loadLocalEnvironment()

	if got := os.Getenv("AGENTMESH_LOCAL_ENV_TEST"); got != "process-value" {
		t.Fatalf("real process environment must win, got %q", got)
	}
}
