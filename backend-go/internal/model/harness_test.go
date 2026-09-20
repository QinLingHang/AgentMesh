package model

import (
	"encoding/json"
	"testing"
)

func TestHarnessConfigNormalizeDefaults(t *testing.T) {
	config := HarnessConfig{}

	if err := config.Normalize(); err != nil {
		t.Fatalf("normalize returned error: %v", err)
	}

	if config.Mode != HarnessModeOff {
		t.Fatalf("empty mode must normalize to OFF, got %q", config.Mode)
	}

	if config.MaxSteps != 12 || config.MaxRepairs != 2 || config.MaxRetriesPerTool != 1 ||
		config.MaxReschedules != 1 || config.LoopRepeatThreshold != 2 {
		t.Fatalf("contract defaults not applied: %+v", config)
	}

	if config.PolicyVersion == "" {
		t.Fatalf("policy version must default to the current release")
	}
}

func TestHarnessConfigNormalizeValidModes(t *testing.T) {
	for _, mode := range []string{"off", "OFF", "observe", "OBSERVE", "enforce", "ENFORCE", "auto_repair", "AUTO_REPAIR"} {
		config := HarnessConfig{Mode: mode}

		if err := config.Normalize(); err != nil {
			t.Fatalf("mode %q must be accepted: %v", mode, err)
		}
	}
}

func TestHarnessConfigNormalizeRejectsUnknownMode(t *testing.T) {
	config := HarnessConfig{Mode: "SUPER_MODE"}

	if err := config.Normalize(); err == nil {
		t.Fatalf("unknown mode must be rejected")
	}
}

func TestHarnessConfigIsOff(t *testing.T) {
	var nilConfig *HarnessConfig

	if !nilConfig.IsOff() {
		t.Fatalf("nil snapshot reads as OFF for legacy tasks")
	}

	observe := HarnessConfig{Mode: HarnessModeObserve}

	if observe.IsOff() {
		t.Fatalf("OBSERVE must not read as OFF")
	}
}

func TestHarnessConfigJSONRoundTrip(t *testing.T) {
	raw := `{"mode":"AUTO_REPAIR","maxSteps":16,"maxRepairs":2,"maxRetriesPerTool":1,"maxReschedules":1,"loopRepeatThreshold":2,"resultSchema":{"type":"object"},"policyVersion":"p37-v1.0"}`

	config := HarnessConfig{}

	if err := json.Unmarshal([]byte(raw), &config); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}

	if config.Mode != HarnessModeAutoRepair || config.MaxSteps != 16 || config.ResultSchema == nil {
		t.Fatalf("unexpected snapshot: %+v", config)
	}

	out, err := json.Marshal(&config)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}

	var back HarnessConfig

	if err := json.Unmarshal(out, &back); err != nil {
		t.Fatalf("re-marshal round trip failed: %v", err)
	}

	if back.Mode != config.Mode || back.MaxSteps != config.MaxSteps ||
		back.MaxRepairs != config.MaxRepairs || back.MaxRetriesPerTool != config.MaxRetriesPerTool ||
		back.MaxReschedules != config.MaxReschedules || back.LoopRepeatThreshold != config.LoopRepeatThreshold ||
		back.PolicyVersion != config.PolicyVersion || back.ResultSchema == nil {
		t.Fatalf("round trip mismatch: %+v vs %+v", back, config)
	}
}

func TestToolHarnessContractJSON(t *testing.T) {
	raw := `{
		"id": 1,
		"name": "create_order",
		"protocol": "internal",
		"inputSchema": {"type": "object"},
		"outputSchema": {"type": "object", "required": ["orderId"]},
		"sideEffectRisk": "NON_IDEMPOTENT_WRITE",
		"supportsIdempotencyKey": false,
		"fallbackToolId": "create_order_v2",
		"argumentAliases": {"order_id": "orderId"}
	}`

	tool := Tool{}

	if err := json.Unmarshal([]byte(raw), &tool); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}

	if tool.SideEffectRisk != HarnessSideEffectNonIdempotentWrite {
		t.Fatalf("side effect risk not decoded: %+v", tool)
	}

	if tool.FallbackToolID != "create_order_v2" {
		t.Fatalf("fallback tool id not decoded: %+v", tool)
	}

	if tool.ArgumentAliases["order_id"] != "orderId" {
		t.Fatalf("argument aliases not decoded: %+v", tool.ArgumentAliases)
	}

	if tool.OutputSchema == nil {
		t.Fatalf("output schema not decoded")
	}

	if tool.SupportsIdempotencyKey {
		t.Fatalf("idempotency key flag must round trip false")
	}
}
