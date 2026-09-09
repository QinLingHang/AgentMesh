package service

import (
	"context"
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
)

type desktopToolRepo struct {
	nextID int64
	tools  map[int64]model.Tool
}

func newDesktopToolRepo() *desktopToolRepo {
	return &desktopToolRepo{nextID: 1, tools: map[int64]model.Tool{}}
}

func (r *desktopToolRepo) CreateTool(_ context.Context, uid int64, tool model.Tool) (*model.Tool, error) {
	tool.ID = r.nextID
	r.nextID++
	tool.UserID = uid
	r.tools[tool.ID] = tool
	copy := tool
	return &copy, nil
}

func (r *desktopToolRepo) ListTools(_ context.Context, uid int64, enabledOnly bool) ([]model.Tool, error) {
	out := []model.Tool{}
	for _, tool := range r.tools {
		if tool.UserID != uid || (enabledOnly && !tool.Enabled) {
			continue
		}
		out = append(out, tool)
	}
	return out, nil
}

func (r *desktopToolRepo) ToolByID(_ context.Context, uid, id int64) (*model.Tool, error) {
	tool, ok := r.tools[id]
	if !ok || tool.UserID != uid {
		return nil, nil
	}
	copy := tool
	return &copy, nil
}

func (r *desktopToolRepo) UpdateTool(_ context.Context, uid, id int64, tool model.Tool) (*model.Tool, error) {
	existing, ok := r.tools[id]
	if !ok || existing.UserID != uid {
		return nil, nil
	}
	tool.ID = id
	tool.UserID = uid
	r.tools[id] = tool
	copy := tool
	return &copy, nil
}

func (r *desktopToolRepo) DeleteTool(_ context.Context, uid, id int64) (bool, error) {
	tool, ok := r.tools[id]
	if !ok || tool.UserID != uid {
		return false, nil
	}
	delete(r.tools, id)
	return true, nil
}

func TestDesktopAgentSeedAndReservedSecurityContract(t *testing.T) {
	ctx := context.Background()
	repo := newDesktopToolRepo()
	service := NewToolService(repo)

	seeded, err := service.SeedDesktop(ctx, 7)
	if err != nil {
		t.Fatal(err)
	}
	if len(seeded) != 47 {
		t.Fatalf("expected 47 complete desktop agent tools, got %d", len(seeded))
	}

	byName := map[string]model.Tool{}
	for _, tool := range seeded {
		byName[tool.Name] = tool
	}
	if byName["local.fs.read"].RiskLevel != "low" || byName["local.fs.read"].RequiresConfirmation {
		t.Fatal("read tool must remain low-risk without confirmation")
	}
	if byName["local.fs.write"].RiskLevel != "medium" || !byName["local.fs.write"].RequiresConfirmation {
		t.Fatal("write tool must require confirmation")
	}
	statusSchema := byName["local.tool.status"].InputSchema
	properties, _ := statusSchema["properties"].(map[string]any)
	if _, ok := properties["waitSeconds"]; !ok {
		t.Fatal("local.tool.status must support bounded long-poll waitSeconds")
	}
	for _, name := range []string{
		"local.fs.delete",
		"local.app.close",
		"local.tool.run",
		"local.terminal.run",
		"local.ui.session.start",
		"local.ui.window.close",
	} {
		tool := byName[name]
		if tool.RiskLevel != "high" || !tool.RequiresConfirmation {
			t.Fatalf("%s must remain high-risk and require confirmation", name)
		}
	}

	if _, err := service.Create(ctx, 7, model.Tool{Name: "local.ui.fake", Protocol: "internal", RiskLevel: "low", Enabled: true}); err == nil {
		t.Fatal("reserved local.* namespace must not be user-creatable")
	}

	runTool := byName["local.tool.run"]
	updated, err := service.Update(ctx, 7, runTool.ID, model.Tool{
		Name:                 "renamed-and-weakened",
		Protocol:             "internal",
		RiskLevel:            "low",
		RequiresConfirmation: false,
		Enabled:              false,
	})
	if err != nil {
		t.Fatal(err)
	}
	if updated.Name != "local.tool.run" || updated.RiskLevel != "high" || !updated.RequiresConfirmation {
		t.Fatal("reserved desktop tool security contract was weakened")
	}
	if updated.Enabled {
		t.Fatal("user should still be able to disable an official desktop tool")
	}

	if err := service.Delete(ctx, 7, runTool.ID); err == nil {
		t.Fatal("official desktop tools must be disabled rather than deleted")
	}
}
