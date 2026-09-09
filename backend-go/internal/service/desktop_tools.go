package service

import (
	"context"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
)

const desktopToolPrefix = "local."

func isReservedDesktopToolName(name string) bool {
	return strings.HasPrefix(strings.ToLower(strings.TrimSpace(name)), desktopToolPrefix)
}

func desktopObjectSchema(properties map[string]any, required ...string) map[string]any {
	if properties == nil {
		properties = map[string]any{}
	}
	return map[string]any{
		"type":                 "object",
		"properties":           properties,
		"required":             required,
		"additionalProperties": false,
	}
}

func desktopPathSchema(extra map[string]any, required ...string) map[string]any {
	properties := map[string]any{
		"path": map[string]any{
			"type":        "string",
			"description": "Absolute path inside a folder explicitly authorized in AgentMesh Desktop Bridge.",
		},
	}
	for key, value := range extra {
		properties[key] = value
	}
	fields := []string{"path"}
	fields = append(fields, required...)
	return desktopObjectSchema(properties, fields...)
}

func desktopSessionSchema(extra map[string]any, required ...string) map[string]any {
	properties := map[string]any{
		"sessionId": map[string]any{
			"type":        "string",
			"description": "Active computer-use session id returned by local.ui.session.start.",
		},
	}
	for key, value := range extra {
		properties[key] = value
	}
	fields := []string{"sessionId"}
	fields = append(fields, required...)
	return desktopObjectSchema(properties, fields...)
}

func desktopTool(
	name string,
	description string,
	inputSchema map[string]any,
	riskLevel string,
	requiresConfirmation bool,
) model.Tool {
	return model.Tool{
		Name:                 name,
		Description:          description,
		Protocol:             "internal",
		InputSchema:          inputSchema,
		RiskLevel:            riskLevel,
		RequiresConfirmation: requiresConfirmation,
		Enabled:              true,
	}
}

func desktopToolDefinitions() []model.Tool {
	stringProp := func() map[string]any { return map[string]any{"type": "string"} }
	integerProp := func() map[string]any { return map[string]any{"type": "integer"} }
	booleanProp := func() map[string]any { return map[string]any{"type": "boolean"} }
	arrayProp := func() map[string]any { return map[string]any{"type": "array"} }
	numberProp := func() map[string]any { return map[string]any{"type": "number"} }

	transferSchema := desktopObjectSchema(
		map[string]any{
			"source":      stringProp(),
			"destination": stringProp(),
			"overwrite":   booleanProp(),
		},
		"source",
		"destination",
	)
	processSchema := desktopObjectSchema(map[string]any{"processId": stringProp()}, "processId")
	processStatusSchema := desktopObjectSchema(
		map[string]any{"processId": stringProp(), "waitSeconds": numberProp()},
		"processId",
	)
	appSchema := desktopObjectSchema(map[string]any{"appId": stringProp()}, "appId")
	selectorProps := func() map[string]any {
		return map[string]any{
			"handle":       integerProp(),
			"name":         stringProp(),
			"controlType":  stringProp(),
			"automationId": stringProp(),
		}
	}
	merge := func(base map[string]any, extra map[string]any) map[string]any {
		out := map[string]any{}
		for key, value := range base {
			out[key] = value
		}
		for key, value := range extra {
			out[key] = value
		}
		return out
	}

	return []model.Tool{
		// Files
		desktopTool("local.fs.list", "List files and folders in an explicitly authorized local directory.", desktopPathSchema(map[string]any{"limit": integerProp()}), "low", false),
		desktopTool("local.fs.stat", "Read metadata for an explicitly authorized local file or folder.", desktopPathSchema(nil), "low", false),
		desktopTool("local.fs.read", "Read a text file from an explicitly authorized local directory.", desktopPathSchema(map[string]any{"maxBytes": integerProp()}), "low", false),
		desktopTool("local.fs.search", "Search file names and bounded text content under an explicitly authorized local directory.", desktopPathSchema(map[string]any{"query": stringProp(), "namePattern": stringProp(), "recursive": booleanProp(), "maxResults": integerProp()}), "low", false),
		desktopTool("local.fs.write", "Create or replace a UTF-8 text file in an explicitly authorized local directory.", desktopPathSchema(map[string]any{"content": stringProp(), "overwrite": booleanProp(), "createParents": booleanProp()}, "content"), "medium", true),
		desktopTool("local.fs.mkdir", "Create a folder in an explicitly authorized local directory.", desktopPathSchema(map[string]any{"parents": booleanProp()}), "medium", true),
		desktopTool("local.fs.copy", "Copy a local file or folder between explicitly authorized locations.", transferSchema, "medium", true),
		desktopTool("local.fs.move", "Move or rename a local file or folder between explicitly authorized locations.", transferSchema, "high", true),
		desktopTool("local.fs.delete", "Delete a local file or folder from an explicitly authorized location.", desktopPathSchema(map[string]any{"recursive": booleanProp()}), "high", true),

		// Applications
		desktopTool("local.app.list", "List local applications currently registered by Desktop Bridge.", desktopObjectSchema(nil), "low", false),
		desktopTool("local.app.discover", "Rescan known Windows applications without launching them.", desktopObjectSchema(nil), "low", false),
		desktopTool("local.app.launch", "Launch a registered local application. Application launch requires explicit approval.", desktopObjectSchema(map[string]any{"appId": stringProp(), "args": arrayProp()}, "appId"), "medium", true),
		desktopTool("local.app.open", "Open an authorized local file/folder with a registered application.", desktopObjectSchema(map[string]any{"appId": stringProp(), "path": stringProp()}, "appId", "path"), "medium", true),
		desktopTool("local.app.status", "List currently running instances of registered local applications.", desktopObjectSchema(map[string]any{"appId": stringProp()}), "low", false),
		desktopTool("local.app.focus", "Bring a visible registered application window to the foreground.", appSchema, "low", false),
		desktopTool("local.app.close", "Close a registered local application process. Unsaved work may be lost.", desktopObjectSchema(map[string]any{"appId": stringProp(), "pid": integerProp()}, "appId"), "high", true),

		// CLI tools
		desktopTool("local.tool.list", "List registered local CLI tools such as Python, Git, Go, Node and FFmpeg.", desktopObjectSchema(nil), "low", false),
		desktopTool("local.tool.discover", "Rescan the local PATH for approved known CLI tool families.", desktopObjectSchema(nil), "low", false),
		desktopTool("local.tool.run", "Run a registered local CLI executable with argv and an authorized working directory. This is code execution and always requires approval.", desktopObjectSchema(map[string]any{"toolId": stringProp(), "args": arrayProp(), "cwd": stringProp(), "waitSeconds": numberProp()}, "toolId"), "high", true),
		desktopTool("local.tool.status", "Wait briefly for, then read bounded stdout/stderr and status for a process started by local.tool.run.", processStatusSchema, "low", false),
		desktopTool("local.tool.cancel", "Cancel a process started by local.tool.run.", processSchema, "medium", true),

		// Advanced terminal
		desktopTool("local.terminal.run", "Run an arbitrary terminal command only when the user explicitly enables advanced terminal mode. Always high risk and approved per action.", desktopObjectSchema(map[string]any{"command": stringProp(), "cwd": stringProp(), "waitSeconds": numberProp()}, "command"), "high", true),
		desktopTool("local.terminal.status", "Wait briefly for, then read bounded output/status for an approved advanced terminal process.", processStatusSchema, "low", false),
		desktopTool("local.terminal.cancel", "Cancel an approved advanced terminal process.", processSchema, "high", true),

		// Computer Use session and screen/window control
		desktopTool("local.ui.session.start", "Start a time-bounded local Computer Use session. This explicit grant gates screen, window, mouse, keyboard and UI Automation actions.", desktopObjectSchema(map[string]any{"durationSeconds": integerProp()}), "high", true),
		desktopTool("local.ui.session.status", "Check whether a known local Computer Use session is still active.", desktopObjectSchema(map[string]any{"sessionId": stringProp()}, "sessionId"), "low", false),
		desktopTool("local.ui.session.stop", "Immediately stop the active local Computer Use session.", desktopSessionSchema(nil), "low", false),
		desktopTool("local.ui.screen.capture", "Capture the current desktop for visual reasoning. Screenshot bytes are request-local and omitted from trace.", desktopSessionSchema(nil), "low", false),
		desktopTool("local.ui.window.list", "List visible Windows desktop windows in an active Computer Use session.", desktopSessionSchema(map[string]any{"limit": integerProp()}), "low", false),
		desktopTool("local.ui.window.info", "Read metadata for a visible desktop window.", desktopSessionSchema(map[string]any{"handle": integerProp()}, "handle"), "low", false),
		desktopTool("local.ui.window.focus", "Focus a visible desktop window.", desktopSessionSchema(map[string]any{"handle": integerProp()}, "handle"), "medium", false),
		desktopTool("local.ui.window.close", "Close a visible desktop window. Unsaved work may be lost.", desktopSessionSchema(map[string]any{"handle": integerProp()}, "handle"), "high", true),

		// Mouse / keyboard
		desktopTool("local.ui.mouse.move", "Move the mouse pointer inside the current desktop.", desktopSessionSchema(map[string]any{"x": integerProp(), "y": integerProp(), "durationMs": integerProp()}, "x", "y"), "medium", false),
		desktopTool("local.ui.mouse.click", "Click the mouse in an active Computer Use session.", desktopSessionSchema(map[string]any{"x": integerProp(), "y": integerProp(), "button": stringProp(), "clicks": integerProp()}, "x", "y"), "medium", false),
		desktopTool("local.ui.mouse.double_click", "Double-click the left mouse button in an active Computer Use session.", desktopSessionSchema(map[string]any{"x": integerProp(), "y": integerProp()}, "x", "y"), "medium", false),
		desktopTool("local.ui.mouse.right_click", "Right-click the mouse in an active Computer Use session.", desktopSessionSchema(map[string]any{"x": integerProp(), "y": integerProp()}, "x", "y"), "medium", false),
		desktopTool("local.ui.mouse.drag", "Drag with the left mouse button between desktop coordinates.", desktopSessionSchema(map[string]any{"startX": integerProp(), "startY": integerProp(), "endX": integerProp(), "endY": integerProp(), "durationMs": integerProp()}, "startX", "startY", "endX", "endY"), "medium", false),
		desktopTool("local.ui.mouse.scroll", "Scroll the current desktop view.", desktopSessionSchema(map[string]any{"amount": integerProp(), "x": integerProp(), "y": integerProp()}, "amount"), "medium", false),
		desktopTool("local.ui.keyboard.type", "Type text into the focused UI without using the clipboard.", desktopSessionSchema(map[string]any{"text": stringProp(), "intervalMs": integerProp()}, "text"), "medium", false),
		desktopTool("local.ui.keyboard.press", "Press a keyboard key in an active Computer Use session.", desktopSessionSchema(map[string]any{"key": stringProp(), "presses": integerProp()}, "key"), "medium", false),
		desktopTool("local.ui.keyboard.hotkey", "Send a bounded keyboard shortcut; dangerous system shortcuts are blocked by the bridge.", desktopSessionSchema(map[string]any{"keys": arrayProp()}, "keys"), "medium", false),
		desktopTool("local.ui.wait", "Wait briefly for a local application UI to update.", desktopSessionSchema(map[string]any{"milliseconds": integerProp()}, "milliseconds"), "low", false),

		// Windows UI Automation
		desktopTool("local.ui.element.find", "Find Windows UI Automation elements by name/control type/automation id.", desktopSessionSchema(merge(selectorProps(), map[string]any{"limit": integerProp()}), "handle"), "low", false),
		desktopTool("local.ui.element.click", "Click a Windows UI Automation element.", desktopSessionSchema(selectorProps(), "handle"), "medium", false),
		desktopTool("local.ui.element.set_text", "Set text on a Windows UI Automation element without reading the clipboard.", desktopSessionSchema(merge(selectorProps(), map[string]any{"value": stringProp()}), "handle", "value"), "medium", false),
		desktopTool("local.ui.element.invoke", "Invoke a Windows UI Automation element action.", desktopSessionSchema(selectorProps(), "handle"), "medium", false),
		desktopTool("local.ui.element.select", "Select a Windows UI Automation element or option.", desktopSessionSchema(merge(selectorProps(), map[string]any{"value": stringProp()}), "handle"), "medium", false),
	}
}

func desktopDefinitionByName(name string) (model.Tool, bool) {
	for _, definition := range desktopToolDefinitions() {
		if definition.Name == name {
			return definition, true
		}
	}
	return model.Tool{}, false
}

// SeedDesktop installs or repairs the complete official Desktop Agent contract.
// It is idempotent and preserves only the user's enabled/disabled choice while
// restoring security-critical name/schema/protocol/risk/confirmation fields.
func (s *ToolService) SeedDesktop(ctx context.Context, uid int64) ([]model.Tool, error) {
	existing, err := s.repo.ListTools(ctx, uid, false)
	if err != nil {
		return nil, err
	}

	byName := map[string]model.Tool{}
	for _, tool := range existing {
		byName[tool.Name] = tool
	}

	result := make([]model.Tool, 0, len(desktopToolDefinitions()))
	for _, definition := range desktopToolDefinitions() {
		if current, ok := byName[definition.Name]; ok {
			definition.Enabled = current.Enabled
			updated, updateErr := s.repo.UpdateTool(ctx, uid, current.ID, normalizeTool(definition))
			if updateErr != nil {
				return nil, updateErr
			}
			if updated != nil {
				result = append(result, *updated)
			}
			continue
		}

		created, createErr := s.repo.CreateTool(ctx, uid, normalizeTool(definition))
		if createErr != nil {
			return nil, createErr
		}
		result = append(result, *created)
	}

	return result, nil
}
