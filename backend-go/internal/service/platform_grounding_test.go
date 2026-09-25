package service

import "testing"

func TestConversationReliabilityPlatformCapabilityQuestionsUseFullRuntime(t *testing.T) {
	cases := []string{
		"我怎么在你这个系统上进行插件化",
		"当前界面有工作流吗",
		"你能直接给我操作吗",
		"How do plugins work on this platform?",
	}

	for _, task := range cases {
		if ShouldUseInteractiveFastPath(task, nil) {
			t.Fatalf("platform capability question must use full runtime: %q", task)
		}
	}
}

func TestConversationReliabilityOrdinaryKnowledgeQuestionKeepsInteractiveFastPath(t *testing.T) {
	if !ShouldUseInteractiveFastPath("请解释 Transformer 的注意力机制", nil) {
		t.Fatal("ordinary knowledge question should keep interactive fast path")
	}
}
