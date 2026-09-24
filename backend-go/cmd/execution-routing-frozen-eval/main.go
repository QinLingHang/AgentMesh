package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"example.com/agentmesh-control-plane/internal/service"
)

type evalCase struct {
	CaseID    string `json:"caseId"`
	Query     string `json:"query"`
	FixtureID string `json:"fixtureId"`
}

type catalog struct {
	Fixtures []struct {
		FixtureID   string            `json:"fixtureId"`
		Attachments []json.RawMessage `json:"attachments"`
	} `json:"fixtures"`
}

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "usage: routing-frozen-router-eval DATASET FIXTURES OUTPUT")
		os.Exit(2)
	}
	fixtureData, err := os.ReadFile(os.Args[2])
	if err != nil {
		panic(err)
	}
	var fixtures catalog
	if err := json.Unmarshal(fixtureData, &fixtures); err != nil {
		panic(err)
	}
	attachmentCount := map[string]int{}
	for _, fixture := range fixtures.Fixtures {
		attachmentCount[fixture.FixtureID] = len(fixture.Attachments)
	}
	in, err := os.Open(os.Args[1])
	if err != nil {
		panic(err)
	}
	defer in.Close()
	out, err := os.Create(os.Args[3])
	if err != nil {
		panic(err)
	}
	defer out.Close()
	encoder := json.NewEncoder(out)
	scanner := bufio.NewScanner(in)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		var item evalCase
		if err := json.Unmarshal(scanner.Bytes(), &item); err != nil {
			panic(err)
		}
		ids := make([]int64, attachmentCount[item.FixtureID])
		started := time.Now()
		fast := service.ShouldUseInteractiveFastPath(item.Query, ids)
		latency := time.Since(started)
		route := "RUNTIME"
		if fast {
			route = "FAST_PATH"
		}
		if err := encoder.Encode(map[string]any{
			"caseId": item.CaseID, "route": route, "handling": "EXECUTE",
			"latencyUs":  float64(latency.Nanoseconds()) / 1000.0,
			"modelCalls": 0, "source": "LEGACY_GO_SHOULD_USE_INTERACTIVE_FAST_PATH",
		}); err != nil {
			panic(err)
		}
	}
	if err := scanner.Err(); err != nil {
		panic(err)
	}
}
