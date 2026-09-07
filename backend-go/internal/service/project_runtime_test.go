package service

import (
	"example.com/agentmesh-control-plane/internal/model"
	"reflect"
	"testing"
)

func TestProjectRuntimeFiltersSelectedResources(t *testing.T) {
	ctx := &model.ProjectRuntimeContext{
		ProjectID: 8,
		AgentMode: "selected", AgentIDs: []int64{2},
		ToolMode: "selected", ToolIDs: []int64{11},
		MCPMode: "selected", MCPServerIDs: []int64{22},
	}
	agents, tools, mcps := filterProjectRuntimeResources(
		ctx,
		[]model.Agent{{ID: 1}, {ID: 2}},
		[]model.Tool{{ID: 10}, {ID: 11}},
		[]model.MCPServer{{ID: 21}, {ID: 22}},
	)
	if len(agents) != 1 || agents[0].ID != 2 {
		t.Fatalf("agents=%v", agents)
	}
	if len(tools) != 1 || tools[0].ID != 11 {
		t.Fatalf("tools=%v", tools)
	}
	if len(mcps) != 1 || mcps[0].ID != 22 {
		t.Fatalf("mcps=%v", mcps)
	}
}

func TestP2MissingBindingsNeverCreateRuntimeResources(t *testing.T) {
	for _, mode := range []string{"all", "selected"} {
		t.Run(mode, func(t *testing.T) {
			ctx := &model.ProjectRuntimeContext{AgentMode: mode, AgentIDs: []int64{999}, ToolMode: mode, ToolIDs: []int64{999}, MCPMode: mode, MCPServerIDs: []int64{999}}
			a, tools, m := filterProjectRuntimeResources(ctx, []model.Agent{{ID: 1}}, []model.Tool{{ID: 2}}, []model.MCPServer{{ID: 3}})
			want := 0
			if mode == "all" {
				want = 1
			}
			if len(a) != want || len(tools) != want || len(m) != want {
				t.Fatalf("missing bindings changed pool: %v %v %v", a, tools, m)
			}
		})
	}
}

func TestP2BindingNormalization(t *testing.T) {
	for _, mode := range []string{"all", "selected"} {
		cfg, err := normalizeProjectRuntimeConfig(model.ProjectRuntimeConfig{AgentMode: mode, ToolMode: mode, MCPMode: mode, AgentIDs: []int64{-1, 0, 2, 2}, ToolIDs: []int64{0, 2, 2}, MCPServerIDs: []int64{2, -1, 2}})
		if err != nil {
			t.Fatal(err)
		}
		want := []int64{2}
		if mode == "all" {
			want = []int64{}
		}
		if !reflect.DeepEqual(cfg.AgentIDs, want) || !reflect.DeepEqual(cfg.ToolIDs, want) || !reflect.DeepEqual(cfg.MCPServerIDs, want) {
			t.Fatalf("normalization: %+v", cfg)
		}
	}
}

func TestProjectPolicyOverridesComposerOnlyWhenLocked(t *testing.T) {
	input := RunTaskInput{
		Scheduler: "greedy", Planner: "heuristic", ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 100, MaxCost: .1, MinQuality: .5},
	}
	ctx := &model.ProjectRuntimeContext{Policy: model.ProjectRuntimePolicy{
		Mode: "project", Scheduler: "adaptive", Planner: "multi_objective", ExecutionMode: "parallel", SynthesisMode: "always",
		Constraints: model.TaskConstraints{MaxLatencyMS: 9000, MaxCost: .2, MinQuality: .9},
	}}
	applyProjectRuntimePolicy(&input, ctx)
	if input.Scheduler != "adaptive" || input.Planner != "multi_objective" || input.ExecutionMode != "parallel" || input.SynthesisMode != "always" {
		t.Fatalf("policy not applied: %+v", input)
	}
	if input.Constraints.MaxLatencyMS != 9000 || input.Constraints.MinQuality != .9 {
		t.Fatalf("constraints=%+v", input.Constraints)
	}
}

func TestNonProjectKeepsAccountResources(t *testing.T) {
	agents := []model.Agent{{ID: 1}, {ID: 2}}
	tools := []model.Tool{{ID: 10}}
	mcps := []model.MCPServer{{ID: 20}}
	gotA, gotT, gotM := filterProjectRuntimeResources(nil, agents, tools, mcps)
	if len(gotA) != 2 || len(gotT) != 1 || len(gotM) != 1 {
		t.Fatal("non-project resources changed")
	}
}
