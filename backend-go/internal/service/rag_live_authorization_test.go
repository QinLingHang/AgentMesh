package service

import (
	"reflect"
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
)

func TestRagLiveAuthorizationRequiresCurrentOwnershipAndConversationProject(t *testing.T) {
	projectID, otherProject := int64(31), int64(32)
	scope := &model.RuntimeKnowledgeScope{UserID: 7, ProjectID: &projectID}
	bases := []model.KnowledgeBase{
		{ID: 1, Scope: model.KnowledgeBaseScopeProject, ProjectID: &projectID},
		{ID: 2, Scope: model.KnowledgeBaseScopeProject, ProjectID: &otherProject},
		{ID: 3, Scope: model.KnowledgeBaseScopeGlobal, UserID: 7},
		{ID: 4, Scope: model.KnowledgeBaseScopeGlobal, UserID: 8},
	}
	got := filterLiveKnowledgeIDs(scope, bases, 7, []int64{4, 3, 2, 1, 1, 999})
	if !reflect.DeepEqual(got, []int64{1, 3}) {
		t.Fatalf("live authorization leaked inaccessible IDs: %v", got)
	}
	if got := filterLiveKnowledgeIDs(scope, bases, 8, []int64{1, 3}); len(got) != 0 {
		t.Fatalf("cross-user access not rejected: %v", got)
	}
	scope.ProjectID = nil
	if got := filterLiveKnowledgeIDs(scope, bases, 7, []int64{1, 3}); !reflect.DeepEqual(got, []int64{3}) {
		t.Fatalf("project knowledge leaked into non-project conversation: %v", got)
	}
}
