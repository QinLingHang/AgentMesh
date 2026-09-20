package model

import (
	"errors"
	"strings"
)

// =========================================================
// P37 Agent Harness
//
// HarnessConfig is frozen into an immutable snapshot when a task is
// created. Queueing, restart, resume and replay all reuse the same
// snapshot; consumers must never recompute it from current system
// defaults. Legacy tasks without a snapshot read as OFF.
// =========================================================

var ErrInvalidHarnessMode = errors.New("invalid harness mode")

const (
	HarnessModeOff         = "OFF"
	HarnessModeObserve     = "OBSERVE"
	HarnessModeEnforce     = "ENFORCE"
	HarnessModeAutoRepair  = "AUTO_REPAIR"

	HarnessSideEffectReadOnly           = "READ_ONLY"
	HarnessSideEffectIdempotentWrite    = "IDEMPOTENT_WRITE"
	HarnessSideEffectNonIdempotentWrite = "NON_IDEMPOTENT_WRITE"
	HarnessSideEffectUnknown            = "UNKNOWN"
)

type HarnessConfig struct {
	// OFF | OBSERVE | ENFORCE | AUTO_REPAIR
	Mode string `json:"mode"`

	MaxSteps int `json:"maxSteps,omitempty"`

	// Only meaningful for AUTO_REPAIR.
	MaxRepairs int `json:"maxRepairs,omitempty"`

	MaxRetriesPerTool int `json:"maxRetriesPerTool,omitempty"`

	MaxReschedules int `json:"maxReschedules,omitempty"`

	LoopRepeatThreshold int `json:"loopRepeatThreshold,omitempty"`

	// Optional JSON Schema the final result must satisfy. Empty means only
	// the configured explicit business rules run.
	ResultSchema map[string]any `json:"resultSchema,omitempty"`

	PolicyVersion string `json:"policyVersion,omitempty"`
}

// Normalize validates and clamps a harness config in place. It returns an
// error for an unknown mode; missing numeric fields fall back to the P37
// contract defaults. A nil receiver is invalid at the call site, not here.
func (c *HarnessConfig) Normalize() error {
	if c == nil {
		return nil
	}

	c.Mode = strings.ToUpper(strings.TrimSpace(c.Mode))

	switch c.Mode {
	case "":
		c.Mode = HarnessModeOff
	case HarnessModeOff, HarnessModeObserve, HarnessModeEnforce, HarnessModeAutoRepair:
	default:
		return ErrInvalidHarnessMode
	}

	if c.MaxSteps <= 0 {
		c.MaxSteps = 12
	}

	if c.MaxRepairs <= 0 {
		c.MaxRepairs = 2
	}

	if c.MaxRetriesPerTool <= 0 {
		c.MaxRetriesPerTool = 1
	}

	if c.MaxReschedules <= 0 {
		c.MaxReschedules = 1
	}

	if c.LoopRepeatThreshold <= 0 {
		c.LoopRepeatThreshold = 2
	}

	c.PolicyVersion = strings.TrimSpace(c.PolicyVersion)

	if c.PolicyVersion == "" {
		c.PolicyVersion = "p37-v1.0"
	}

	return nil
}

// IsOff reports whether the snapshot keeps the legacy execution semantics.
func (c *HarnessConfig) IsOff() bool {
	if c == nil {
		return true
	}

	return c.Mode == HarnessModeOff
}

// HarnessSummary is the compact list-page projection of one harness run.
type HarnessSummary struct {
	Mode string `json:"mode"`

	// COMPLETED | TERMINATED | OBSERVED_ISSUES
	Outcome string `json:"outcome"`

	ValidationFailures int `json:"validationFailures"`

	Repairs int `json:"repairs"`

	Retries int `json:"retries"`

	Reschedules int `json:"reschedules"`

	TerminationReason string `json:"terminationReason"`

	OverheadMS int64 `json:"overheadMs"`
}

// HarnessReport is the full aggregated run report (state timeline, events,
// diagnoses, recoveries, metrics). It is persisted and returned as opaque
// JSON so the runtime owns its schema.
type HarnessReport map[string]any
