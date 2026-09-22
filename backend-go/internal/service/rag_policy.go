package service

import (
	"context"
	"sort"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
)

type runtimeKnowledgePolicyRepository interface {
	ResolveRuntimeKnowledgeScope(context.Context, int64, *int64) (*model.RuntimeKnowledgeScope, error)
	ListKnowledgeBases(context.Context, int64) ([]model.KnowledgeBase, error)
}

func normalizeRagPolicy(input model.RagPolicy, hasProject bool) model.RagPolicy {
	mode := model.RagMode(strings.ToUpper(strings.TrimSpace(string(input.Mode))))
	switch mode {
	case model.RagModeOff, model.RagModeOn:
	default:
		mode = model.RagModeAuto
	}

	scopes := make([]model.RagScope, 0, 2)
	seen := map[model.RagScope]bool{}
	for _, raw := range input.Scopes {
		scope := model.RagScope(strings.ToUpper(strings.TrimSpace(string(raw))))
		if scope != model.RagScopeProject && scope != model.RagScopeUserGlobal {
			continue
		}
		if scope == model.RagScopeProject && !hasProject {
			continue
		}
		if !seen[scope] {
			scopes = append(scopes, scope)
			seen[scope] = true
		}
	}
	// An omitted scope field uses the project default. An explicit [] means
	// "no knowledge sources" and must not silently re-enable project RAG.
	if input.Scopes == nil && hasProject {
		scopes = append(scopes, model.RagScopeProject)
	}

	selected := make([]int64, 0, len(input.SelectedKnowledgeBaseIDs))
	selectedSeen := map[int64]bool{}
	for _, id := range input.SelectedKnowledgeBaseIDs {
		if id <= 0 || selectedSeen[id] {
			continue
		}
		selectedSeen[id] = true
		selected = append(selected, id)
	}
	sort.Slice(selected, func(i, j int) bool { return selected[i] < selected[j] })

	return model.RagPolicy{
		Mode:                     mode,
		Scopes:                   scopes,
		SelectedKnowledgeBaseIDs: selected,
	}
}

func (s *TaskService) resolveEffectiveRagPolicy(
	ctx context.Context,
	uid int64,
	conversationID *int64,
	requested model.RagPolicy,
) (model.RagPolicy, model.EffectiveRagPolicy, []model.KnowledgeCatalogItem, error) {
	repo, ok := s.tasks.(runtimeKnowledgePolicyRepository)
	if !ok {
		// Isolated tests may use a task-only fixture. Fail closed for governed
		// knowledge while preserving non-RAG execution.
		normalized := normalizeRagPolicy(requested, false)
		return normalized, model.EffectiveRagPolicy{
			Mode:                    normalized.Mode,
			AllowedScopes:           []model.RagScope{},
			AllowedKnowledgeBaseIDs: []int64{},
			ExplicitlySelectedIDs:   []int64{},
			PolicyVersion:           "rag-v1.1",
		}, []model.KnowledgeCatalogItem{}, nil
	}

	runtimeScope, err := repo.ResolveRuntimeKnowledgeScope(ctx, uid, conversationID)
	if err != nil {
		return model.RagPolicy{}, model.EffectiveRagPolicy{}, nil, err
	}
	hasProject := runtimeScope != nil && runtimeScope.ProjectID != nil && *runtimeScope.ProjectID > 0
	normalized := normalizeRagPolicy(requested, hasProject)
	if normalized.Mode == model.RagModeOff {
		// OFF is a hard gate: no catalog metadata is sent to the model/runtime.
		return normalized, model.EffectiveRagPolicy{
			Mode: normalized.Mode, AllowedScopes: []model.RagScope{},
			AllowedKnowledgeBaseIDs: []int64{}, ExplicitlySelectedIDs: []int64{},
			PolicyVersion: "rag-v1.1",
		}, []model.KnowledgeCatalogItem{}, nil
	}

	bases, err := repo.ListKnowledgeBases(ctx, uid)
	if err != nil {
		return model.RagPolicy{}, model.EffectiveRagPolicy{}, nil, err
	}

	allowedScope := map[model.RagScope]bool{}
	for _, scope := range normalized.Scopes {
		allowedScope[scope] = true
	}

	allowedIDs := make([]int64, 0, len(bases))
	catalog := make([]model.KnowledgeCatalogItem, 0, len(bases))
	allowedSet := map[int64]bool{}
	for _, base := range bases {
		var scope model.RagScope
		switch base.Scope {
		case model.KnowledgeBaseScopeProject:
			if !allowedScope[model.RagScopeProject] || !hasProject || base.ProjectID == nil || *base.ProjectID != *runtimeScope.ProjectID {
				continue
			}
			scope = model.RagScopeProject
		case model.KnowledgeBaseScopeGlobal:
			// Global knowledge is opt-in per request. Merely owning a global
			// base or binding it to a project is not enough to activate it.
			// Keep ownership as an additional defense even when a repository
			// implementation accidentally returns an over-broad catalog.
			if !allowedScope[model.RagScopeUserGlobal] || base.UserID != uid {
				continue
			}
			scope = model.RagScopeUserGlobal
		default:
			continue
		}
		allowedIDs = append(allowedIDs, base.ID)
		allowedSet[base.ID] = true
		catalog = append(catalog, model.KnowledgeCatalogItem{
			KnowledgeBaseID: base.ID,
			Name:            base.Name,
			Description:     base.Description,
			Scope:           scope,
			ProjectID:       base.ProjectID,
			Accessible:      true,
		})
	}
	sort.Slice(allowedIDs, func(i, j int) bool { return allowedIDs[i] < allowedIDs[j] })
	sort.Slice(catalog, func(i, j int) bool { return catalog[i].KnowledgeBaseID < catalog[j].KnowledgeBaseID })

	explicit := make([]int64, 0, len(normalized.SelectedKnowledgeBaseIDs))
	for _, id := range normalized.SelectedKnowledgeBaseIDs {
		if !allowedSet[id] {
			return model.RagPolicy{}, model.EffectiveRagPolicy{}, nil, ErrForbidden
		}
		explicit = append(explicit, id)
	}

	effective := model.EffectiveRagPolicy{
		Mode: normalized.Mode,
		// A no-project request has no authorized scopes. Keep the empty slice
		// non-nil: JSON null fails Python RuntimeRequest.allowedScopes (list).
		// Never replace an empty scope with PROJECT or USER_GLOBAL.
		AllowedScopes:           append([]model.RagScope{}, normalized.Scopes...),
		AllowedKnowledgeBaseIDs: allowedIDs,
		ExplicitlySelectedIDs:   explicit,
		PolicyVersion:           "rag-v1.1",
	}
	return normalized, effective, catalog, nil
}

// constrainEffectiveRagPolicyToSnapshot keeps the task-creation snapshot as an
// upper bound while allowing live authorization revocation to take effect.
// Newly granted knowledge bases are deliberately excluded from an already
// queued/suspended task so replay/recovery remains reproducible.
func constrainEffectiveRagPolicyToSnapshot(
	snapshot model.EffectiveRagPolicy,
	live model.EffectiveRagPolicy,
	liveCatalog []model.KnowledgeCatalogItem,
) (model.EffectiveRagPolicy, []model.KnowledgeCatalogItem) {
	upper := map[int64]bool{}
	for _, id := range snapshot.AllowedKnowledgeBaseIDs {
		if id > 0 {
			upper[id] = true
		}
	}
	allowed := make([]int64, 0, len(live.AllowedKnowledgeBaseIDs))
	liveAllowed := map[int64]bool{}
	for _, id := range live.AllowedKnowledgeBaseIDs {
		if upper[id] {
			allowed = append(allowed, id)
			liveAllowed[id] = true
		}
	}
	explicit := make([]int64, 0, len(snapshot.ExplicitlySelectedIDs))
	for _, id := range snapshot.ExplicitlySelectedIDs {
		if liveAllowed[id] {
			explicit = append(explicit, id)
		}
	}
	catalog := make([]model.KnowledgeCatalogItem, 0, len(liveCatalog))
	for _, item := range liveCatalog {
		if liveAllowed[item.KnowledgeBaseID] {
			catalog = append(catalog, item)
		}
	}
	return model.EffectiveRagPolicy{
		Mode: snapshot.Mode,
		// Resume/revocation must preserve the same [] JSON transport contract.
		AllowedScopes:           append([]model.RagScope{}, snapshot.AllowedScopes...),
		AllowedKnowledgeBaseIDs: allowed,
		ExplicitlySelectedIDs:   explicit,
		PolicyVersion:           snapshot.PolicyVersion,
	}, catalog
}
