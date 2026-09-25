package service

import "testing"

func TestShouldUseInteractiveFastPathAutonomousCapabilityRouting(t *testing.T) {
	t.Parallel()

	agentic := []string{
		"桌面有什么文件",
		"打开 VS Code 帮我看看项目",
		"运行 go test ./...",
		"帮我截图看看当前屏幕",
		"帮我看看 GitHub 上这个 PR",
		"AgentMesh Project BYOK 是怎么设计的",
		"帮我做一次代码审查",
		"查询一下库存还剩多少",
		"帮我计算 382*927",
		"获取最新客户记录",
		"我的简历里主要有哪些项目经历？",
		"秦令杭的简历怎么样？",
		"分析一下我上传的资料",
		"帮我看一下库存",
		"查看当前客户详情",
		"检查一下部署状态",
		`读取 E:\AIProject\AgentMesh_HUMAN_ACCEPTANCE_SANDBOX\demo.txt`,
	}

	for _, task := range agentic {
		if ShouldUseInteractiveFastPath(task, nil) {
			t.Fatalf("agentic task incorrectly routed to interactive fast path: %q", task)
		}
	}

	general := []string{
		"Python 和 Java 有什么区别？",
		"什么是哈希表？",
		"帮我解释一下 TCP 三次握手",
		"帮我解释最大子数组和为什么能用动态规划",
	}

	for _, task := range general {
		if !ShouldUseInteractiveFastPath(task, nil) {
			t.Fatalf("ordinary chat should keep interactive fast path: %q", task)
		}
	}

	if !ShouldUseInteractiveFastPath("总结这个附件", []int64{1}) {
		t.Fatal("request-local attachment analysis should keep interactive fast path")
	}

	if ShouldUseInteractiveFastPath("读取附件后创建一条记录", []int64{1}) {
		t.Fatal("attachment plus capability intent must reach full runtime discovery")
	}
}
