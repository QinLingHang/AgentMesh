package runtime

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// runtimeResponseError keeps upstream validation diagnostics useful without
// copying request values, model credentials, attachment contents or arbitrary
// upstream error text into Go errors, task records, or browser responses.
func runtimeResponseError(resp *http.Response) error {
	fallback := fmt.Errorf("runtime returned %s", resp.Status)
	if resp.StatusCode != http.StatusUnprocessableEntity {
		return fallback
	}

	var reply struct {
		Detail []struct {
			Loc  []any  `json:"loc"`
			Type string `json:"type"`
		} `json:"detail"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 64*1024)).Decode(&reply); err != nil {
		return fallback
	}

	paths := make([]string, 0, 3)
	for _, detail := range reply.Detail {
		path := safeValidationPath(detail.Loc)
		if path == "" || !safeValidationType(detail.Type) {
			continue
		}
		paths = append(paths, path+":"+detail.Type)
		if len(paths) == 3 {
			break
		}
	}
	if len(paths) == 0 {
		return fallback
	}
	return fmt.Errorf("runtime returned %s (validation: %s)", resp.Status, strings.Join(paths, ", "))
}

// Only names from the cross-language transport schema may appear in a
// diagnostic. Unknown nested keys may contain user-controlled content.
func safeValidationPath(loc []any) string {
	if len(loc) < 2 || loc[0] != "body" {
		return ""
	}
	root, ok := loc[1].(string)
	if !ok || !runtimeValidationRoots[root] {
		return ""
	}
	path := root
	for _, part := range loc[2:] {
		switch value := part.(type) {
		case string:
			if !runtimeValidationFields[value] {
				return path
			}
			path += "." + value
		case float64:
			if value != float64(int(value)) || value < 0 || value > 1000 {
				return path
			}
			path += fmt.Sprintf("[%d]", int(value))
		default:
			return path
		}
	}
	return path
}

func safeValidationType(value string) bool {
	if value == "" || len(value) > 48 {
		return false
	}
	for _, char := range value {
		if !(char >= 'a' && char <= 'z' || char >= '0' && char <= '9' || char == '_') {
			return false
		}
	}
	return true
}

var runtimeValidationRoots = map[string]bool{
	"user_id": true, "request_id": true, "conversationId": true,
	"task": true, "history": true, "scheduler": true, "planner": true,
	"executionMode": true, "synthesisMode": true, "constraints": true,
	"ragPolicy": true, "effectiveRagPolicy": true, "knowledgeCatalog": true,
	"agents": true, "tools": true, "mcp_servers": true, "continuation": true,
	"projectModel": true, "modelPool": true, "modelSelection": true,
	"attachments": true,
}

var runtimeValidationFields = map[string]bool{
	"mode": true, "scopes": true, "allowedScopes": true,
	"selectedKnowledgeBaseIds": true, "allowedKnowledgeBaseIds": true,
	"explicitlySelectedIds": true, "policyVersion": true,
	"capabilities": true, "capabilityProfiles": true,
	"name": true, "endpoint": true, "protocol": true,
	"inputSchema": true, "riskLevel": true, "transport": true,
	"content": true, "role": true, "modelName": true,
	"baseUrl": true, "serviceId": true, "maxLatencyMs": true,
	"maxCost": true, "minQuality": true, "enabled": true,
	"knowledgeBaseId": true, "scope": true, "projectId": true,
}
