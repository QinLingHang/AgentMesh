package service

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

// Embed the full repository contract while overriding only the two methods
// actually used by live knowledge authorization. No DB or production state.
type knowledgeRuntimePolicyJSONRepo struct {
	repository.TaskRepository
	projectID *int64
	bases     []model.KnowledgeBase
}

func (r knowledgeRuntimePolicyJSONRepo) ResolveRuntimeKnowledgeScope(_ context.Context, uid int64, conversationID *int64) (*model.RuntimeKnowledgeScope, error) {
	return &model.RuntimeKnowledgeScope{UserID: uid, ConversationID: conversationID, ProjectID: r.projectID}, nil
}

func (r knowledgeRuntimePolicyJSONRepo) ListKnowledgeBases(context.Context, int64) ([]model.KnowledgeBase, error) {
	if r.bases == nil {
		return []model.KnowledgeBase{}, nil
	}
	return r.bases, nil
}

// An uploaded and indexed Global KB is not user consent. Only the explicit
// USER_GLOBAL scope may appear in Go's allowlist and Python's catalog.
// A foreign-owned Global KB must remain excluded even if a broken repository
// accidentally returns it; no implicit ID selection is allowed.
func TestKnowledgeRuntimeGlobalKnowledgeRequiresExplicitScope(t *testing.T) {
	projectID := int64(42)
	repo := knowledgeRuntimePolicyJSONRepo{bases: []model.KnowledgeBase{
		{ID: 10, UserID: 7, Name: "A profile", Scope: model.KnowledgeBaseScopeGlobal, ReadyFileCount: 1},
		{ID: 11, UserID: 8, Name: "B profile", Scope: model.KnowledgeBaseScopeGlobal, ReadyFileCount: 1},
		{ID: 12, UserID: 7, Name: "Project doc", Scope: model.KnowledgeBaseScopeProject, ProjectID: &projectID},
	}}
	svc := &TaskService{tasks: repo}
	for _, tc := range []struct {
		name    string
		project *int64
		scopes  []model.RagScope
		want    []int64
	}{
		{"global uploaded but no opt in", nil, []model.RagScope{model.RagScopeProject}, []int64{}},
		{"global explicitly enabled", nil, []model.RagScope{model.RagScopeProject, model.RagScopeUserGlobal}, []int64{10}},
		{"project alone excludes global", &projectID, []model.RagScope{model.RagScopeProject}, []int64{12}},
		{"project plus global opt in", &projectID, []model.RagScope{model.RagScopeProject, model.RagScopeUserGlobal}, []int64{10, 12}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			repo.projectID = tc.project
			svc.tasks = repo
			requested, effective, catalog, err := svc.resolveEffectiveRagPolicy(context.Background(), 7, nil,
				model.RagPolicy{Mode: model.RagModeAuto, Scopes: tc.scopes})
			if err != nil {
				t.Fatal(err)
			}
			if requested.Mode != model.RagModeAuto {
				t.Fatal("mode was silently changed")
			}
			if !reflect.DeepEqual(effective.AllowedKnowledgeBaseIDs, tc.want) {
				t.Fatalf("unexpected authorized KB IDs: got=%v want=%v", effective.AllowedKnowledgeBaseIDs, tc.want)
			}
			if len(effective.ExplicitlySelectedIDs) != 0 {
				t.Fatal("automatic discovery must not force-select KB IDs")
			}
			if len(catalog) != len(tc.want) {
				t.Fatalf("catalog leaked other owner or scope: %+v", catalog)
			}
			for i, item := range catalog {
				if item.KnowledgeBaseID != tc.want[i] {
					t.Fatalf("wrong catalog item: %+v", item)
				}
			}
		})
	}
}

func TestKnowledgeRuntimeFullRuntimeRAGPolicyJSONArrays(t *testing.T) {
	projectID := int64(42)
	for _, tc := range []struct {
		name       string
		projectID  *int64
		requested  model.RagPolicy
		wantScopes string
	}{
		{name: "no project desktop", wantScopes: `[]`},
		{name: "project explicit none", projectID: &projectID,
			requested: model.RagPolicy{Mode: model.RagModeOn, Scopes: []model.RagScope{}}, wantScopes: `[]`},
		{name: "project default", projectID: &projectID, wantScopes: `["PROJECT"]`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			svc := &TaskService{tasks: knowledgeRuntimePolicyJSONRepo{projectID: tc.projectID}}
			requested, effective, catalog, err := svc.resolveEffectiveRagPolicy(context.Background(), 7, nil, tc.requested)
			if err != nil {
				t.Fatal(err)
			}
			payload, err := json.Marshal(runtimeclient.ExecuteRequest{
				UserID: 7, RequestID: "schema-contract", Task: "list authorized directory",
				RagPolicy: requested, EffectiveRagPolicy: effective,
				KnowledgeCatalog: catalog,
				Agents:           []model.Agent{{ID: 1, Name: "GeneralAgent", Endpoint: "internal://general", Protocol: "internal", Capabilities: []string{"general"}, CapabilityProfiles: []model.AgentCapabilityProfile{}}},
			})
			if err != nil {
				t.Fatal(err)
			}
			var root map[string]json.RawMessage
			if err = json.Unmarshal(payload, &root); err != nil {
				t.Fatal(err)
			}
			if tc.name == "no project desktop" {
				fixtureBytes, err := os.ReadFile("../../../runtime-python/tests/fixtures/go_full_runtime_desktop.json")
				if err != nil {
					t.Fatal(err)
				}
				var fixture map[string]json.RawMessage
				if err := json.Unmarshal(fixtureBytes, &fixture); err != nil {
					t.Fatal(err)
				}
				for _, policy := range []string{"effectiveRagPolicy", "ragPolicy"} {
					var expected, actual any
					if err := json.Unmarshal(fixture[policy], &expected); err != nil {
						t.Fatal(err)
					}
					if err := json.Unmarshal(root[policy], &actual); err != nil {
						t.Fatal(err)
					}
					if !reflect.DeepEqual(expected, actual) {
						t.Fatalf("Go %s diverged from shared Python contract fixture: expected=%v got=%v", policy, expected, actual)
					}
				}
			}
			for _, field := range []struct {
				parent string
				name   string
				want   string
			}{
				{"ragPolicy", "scopes", tc.wantScopes},
				{"ragPolicy", "selectedKnowledgeBaseIds", `[]`},
				{"effectiveRagPolicy", "allowedScopes", tc.wantScopes},
				{"effectiveRagPolicy", "allowedKnowledgeBaseIds", `[]`},
				{"effectiveRagPolicy", "explicitlySelectedIds", `[]`},
			} {
				var object map[string]json.RawMessage
				if err := json.Unmarshal(root[field.parent], &object); err != nil {
					t.Fatal(err)
				}
				if string(object[field.name]) != field.want {
					t.Fatalf("%s.%s must be %s; got %s", field.parent, field.name, field.want, object[field.name])
				}
			}
		})
	}
}

func TestKnowledgeRuntimeFullRuntimeRevocationJSONArrays(t *testing.T) {
	snapshot := model.EffectiveRagPolicy{Mode: model.RagModeAuto, PolicyVersion: "rag-v1.1"}
	effective, catalog := constrainEffectiveRagPolicyToSnapshot(snapshot, snapshot, nil)
	if len(catalog) != 0 {
		t.Fatal("revocation resurrected unauthorized catalog")
	}
	payload, err := json.Marshal(effective)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"allowedScopes", "allowedKnowledgeBaseIds", "explicitlySelectedIds"} {
		if string(fields[field]) != `[]` {
			t.Fatalf("revoked field %s: expected [], got %s", field, fields[field])
		}
	}
}
