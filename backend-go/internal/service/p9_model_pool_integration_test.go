package service

import (
	"context"
	"crypto/rand"
	"strings"
	"testing"

	dbschema "example.com/agentmesh-control-plane/internal/db"
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

func TestPersonalModelPoolLifecycleAndManualRouting(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	if err := dbschema.EnsureUserModelSchema(ctx, database); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-model-pool-master-key")
	if err != nil {
		t.Fatal(err)
	}

	res, err := database.Exec("INSERT INTO users(email,password_hash,display_name) VALUES('p9-model-pool@example.test','fixture','Model Pool')")
	if err != nil {
		t.Fatal(err)
	}
	uid, err := res.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}

	firstSecret := "sk-model-pool-first-secret"
	first, err := governance.CreateUserModelService(ctx, uid, model.UserModelServiceInput{
		Name: "Qwen Primary", Provider: "qwen",
		BaseURL:   "https://dashscope.aliyuncs.com/compatible-mode/v1",
		ModelName: "qwen-plus", VisionModelName: "qwen-vl-plus",
		APIKey: firstSecret, Enabled: true, AutoRoute: true, IsDefault: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if first == nil || first.ID <= 0 || first.MaskedHint == "" || strings.Contains(first.MaskedHint, firstSecret) {
		t.Fatalf("unsafe first model service projection: %+v", first)
	}

	secondSecret := "sk-model-pool-second-secret"
	second, err := governance.CreateUserModelService(ctx, uid, model.UserModelServiceInput{
		Name: "OpenAI Secondary", Provider: "openai-compatible",
		BaseURL: "https://api.openai.com/v1", ModelName: "gpt-4.1-mini",
		APIKey: secondSecret, Enabled: true, AutoRoute: true,
	})
	if err != nil {
		t.Fatal(err)
	}

	items, err := governance.ListUserModelServices(ctx, uid)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 2 {
		t.Fatalf("model pool size=%d want=2 items=%+v", len(items), items)
	}

	var raw []byte
	if err := database.QueryRow("SELECT ciphertext FROM user_model_services WHERE id=?", first.ID).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), firstSecret) {
		t.Fatal("personal model API key stored as plaintext")
	}

	autoPool, err := governance.ResolveUserModelRuntimePool(ctx, uid, model.ModelSelection{Mode: "auto"})
	if err != nil {
		t.Fatal(err)
	}
	if len(autoPool) != 2 {
		t.Fatalf("auto route pool size=%d want=2", len(autoPool))
	}

	manualPool, err := governance.ResolveUserModelRuntimePool(ctx, uid, model.ModelSelection{Mode: "manual", ServiceID: &second.ID})
	if err != nil {
		t.Fatal(err)
	}
	if len(manualPool) != 1 || manualPool[0].ServiceID != second.ID || manualPool[0].APIKey != secondSecret {
		t.Fatalf("manual route mismatch: %+v", manualPool)
	}

	updated, err := governance.UpdateUserModelService(ctx, uid, second.ID, model.UserModelServiceInput{
		Name: "OpenAI Secondary Updated", Provider: "openai-compatible",
		BaseURL: "https://api.openai.com/v1", ModelName: "gpt-4.1-mini",
		APIKey: "", Enabled: true, AutoRoute: false,
	})
	if err != nil {
		t.Fatal(err)
	}
	if updated.AutoRoute {
		t.Fatalf("auto route flag was not updated: %+v", updated)
	}
	manualPool, err = governance.ResolveUserModelRuntimePool(ctx, uid, model.ModelSelection{Mode: "manual", ServiceID: &second.ID})
	if err != nil {
		t.Fatal(err)
	}
	if manualPool[0].APIKey != secondSecret {
		t.Fatal("empty update API key did not preserve encrypted secret")
	}

	autoPool, err = governance.ResolveUserModelRuntimePool(ctx, uid, model.ModelSelection{Mode: "auto"})
	if err != nil {
		t.Fatal(err)
	}
	if len(autoPool) != 1 || autoPool[0].ServiceID != first.ID {
		t.Fatalf("auto route should contain only first service: %+v", autoPool)
	}

	if err := governance.DeleteUserModelService(ctx, uid, second.ID); err != nil {
		t.Fatal(err)
	}
	items, err = governance.ListUserModelServices(ctx, uid)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].ID != first.ID {
		t.Fatalf("delete did not preserve remaining service: %+v", items)
	}

	if _, err := governance.UpdateUserModelService(ctx, uid, first.ID, model.UserModelServiceInput{
		Name: first.Name, Provider: first.Provider, BaseURL: first.BaseURL,
		ModelName: first.ModelName, VisionModelName: first.VisionModelName,
		APIKey: "", Enabled: true, AutoRoute: false, IsDefault: first.IsDefault,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := governance.ResolveUserModelRuntimePool(ctx, uid, model.ModelSelection{Mode: "auto"}); err != ErrModelAutoRouteNotConfigured {
		t.Fatalf("auto route without participating personal services must fail closed, got %v", err)
	}
}

func TestLegacyPersonalModelMigratesOnceAndDoesNotResurrectAfterDelete(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	if err := dbschema.EnsureUserModelSchema(ctx, database); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-model-pool-legacy-master-key")
	if err != nil {
		t.Fatal(err)
	}

	res, err := database.Exec("INSERT INTO users(email,password_hash,display_name) VALUES('p9-model-pool-legacy@example.test','fixture','Legacy Model')")
	if err != nil {
		t.Fatal(err)
	}
	uid, err := res.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}

	secret := "sk-legacy-model-secret"
	nonce := make([]byte, governance.aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		t.Fatal(err)
	}
	ciphertext := governance.aead.Seal(nil, nonce, []byte(secret), userModelAAD(uid))
	if _, err := repo.UpsertUserModelProvider(ctx, model.UserModelProvider{
		UserID: uid, Provider: "qwen",
		BaseURL:   "https://dashscope.aliyuncs.com/compatible-mode/v1",
		ModelName: "qwen-plus", VisionModelName: "qwen-vl-plus",
		MaskedHint: maskHint(secret), Enabled: true,
	}, ciphertext, nonce); err != nil {
		t.Fatal(err)
	}

	items, err := governance.ListUserModelServices(ctx, uid)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].ModelName != "qwen-plus" {
		t.Fatalf("legacy migration mismatch: %+v", items)
	}
	var legacyRows int
	if err := database.QueryRow("SELECT COUNT(*) FROM user_model_providers WHERE user_id=?", uid).Scan(&legacyRows); err != nil {
		t.Fatal(err)
	}
	if legacyRows != 0 {
		t.Fatalf("legacy row retained after migration: %d", legacyRows)
	}

	if err := governance.DeleteUserModelService(ctx, uid, items[0].ID); err != nil {
		t.Fatal(err)
	}
	items, err = governance.ListUserModelServices(ctx, uid)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 0 {
		t.Fatalf("deleted migrated service resurrected: %+v", items)
	}
}
