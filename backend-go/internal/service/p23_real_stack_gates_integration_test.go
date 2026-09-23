package service

import (
	"context"
	"fmt"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func TestP23RealStackCase56AttachmentTrustBoundary(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)

	insert := func(query string, args ...any) int64 {
		t.Helper()
		result, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := result.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}

	uid := insert("INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		fmt.Sprintf("p23-case56-%d@example.test", time.Now().UnixNano()), "fixture", "P23 Case56")
	otherUID := insert("INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		fmt.Sprintf("p23-case56-other-%d@example.test", time.Now().UnixNano()), "fixture", "P23 Case56 Other")
	conversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P23 case56')", uid)
	otherConversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P23 case56 other')", otherUID)

	createAttachment := func(owner, conversation int64, name, ext string, size int64) int64 {
		return insert(`INSERT INTO conversation_attachments(
            user_id, conversation_id, original_name, media_type, extension,
            size_bytes, checksum_sha256, storage_key
        ) VALUES(?,?,?,?,?,?,?,?)`, owner, conversation, name, "text/plain", ext, size,
			fmt.Sprintf("sha-%s", name), fmt.Sprintf("attachments/%d/%d/%s", owner, conversation, name))
	}

	a := createAttachment(uid, conversationID, "policy-a.txt", "txt", 96)
	b := createAttachment(uid, conversationID, "policy-b.txt", "txt", 104)
	foreign := createAttachment(otherUID, otherConversationID, "foreign.txt", "txt", 80)
	tooLarge := createAttachment(uid, conversationID, "large.txt", "txt", 33*1024)
	unsupported := createAttachment(uid, conversationID, "opaque.pdf", "pdf", 100)

	service := NewTaskService(repo, repo, repo, runtimeclient.NewClient("http://127.0.0.1:1", "fixture", time.Second), repo, repo)
	service.SetAttachmentService(NewAttachmentService(repo, nil, 0))

	base := RunTaskInput{ConversationID: &conversationID, Task: "先比较两份文档，识别冲突，再向我询问后才能修改。"}
	base.AttachmentIDs = []int64{a, b}
	if !service.p23ModelReadableAttachments(ctx, uid, base) {
		t.Fatal("two owned bounded text attachments must be eligible for the model-readable FastPath hint")
	}

	duplicate := base
	duplicate.AttachmentIDs = []int64{a, a}
	if service.p23ModelReadableAttachments(ctx, uid, duplicate) {
		t.Fatal("duplicate attachment IDs must not be trusted as two readable documents")
	}

	crossUser := base
	crossUser.AttachmentIDs = []int64{a, foreign}
	if service.p23ModelReadableAttachments(ctx, uid, crossUser) {
		t.Fatal("foreign attachment must never become model-readable for the current user")
	}

	oversized := base
	oversized.AttachmentIDs = []int64{a, tooLarge}
	if service.p23ModelReadableAttachments(ctx, uid, oversized) {
		t.Fatal("attachments above the FastPath document budget must stay out of the model-readable path")
	}

	wrongType := base
	wrongType.AttachmentIDs = []int64{a, unsupported}
	if service.p23ModelReadableAttachments(ctx, uid, wrongType) {
		t.Fatal("non text-like attachment types must not be marked model-readable by the P23 hint")
	}

	missing := base
	missing.AttachmentIDs = []int64{a, 999999999}
	if service.p23ModelReadableAttachments(ctx, uid, missing) {
		t.Fatal("missing attachment IDs must fail closed")
	}
}

func TestP23RealStackCase72ApprovalRejectReusesOriginalTask(t *testing.T) {
	evidence := p23VerifyApprovalRejectHandling(t)
	if evidence["taskIdReused"] != true || evidence["createNewTask"] != false || evidence["writeCount"] != 0 || evidence["replaySideEffect"] != false {
		t.Fatalf("case72 authoritative rejection invariants failed: %+v", evidence)
	}
}

func TestP23RealStackCase56DoesNotChangeFrozenLabelContract(t *testing.T) {
	// Keep the final real-stack gate tied to the reviewed contract: readable
	// request-local documents are model input, not a Tool permission grant.
	proposal := runtimeclient.P23UnderstandingResponse{
		SchemaVersion: "p23.v2", ExecutionRoute: "FAST_PATH", Disposition: "EXECUTE",
		KnowledgeDependency: "NONE", CapabilityRequired: false, AnalysisSource: "RULE",
	}
	decision := P23ExecutionDecision{
		SchemaVersion: "p23.v2", Strategy: "FAST_PATH", Disposition: "EXECUTE",
		RuntimePath: "FAST_PATH", DeliveryMode: "direct", AnalysisSource: "RULE",
	}
	if err := ValidateP23Decision(decision, proposal, model.RagPolicy{Mode: model.RagModeAuto}); err != nil {
		t.Fatalf("reviewed case56 FastPath contract became invalid: %v", err)
	}
}
