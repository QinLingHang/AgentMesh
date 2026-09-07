import { Icon } from "../../components/common/Icon";

const suggestions = [
  {
    icon: "chart" as const,
    title: "分析数据",
    description: "提炼关键指标、趋势与异常",
    prompt: "分析这份数据，提炼关键指标、趋势、异常，并给出结论。",
  },
  {
    icon: "file" as const,
    title: "总结文档",
    description: "从长文中整理结构化重点",
    prompt: "总结这份文档的核心内容，按主题整理重点、结论和待办事项。",
  },
  {
    icon: "search" as const,
    title: "检索知识",
    description: "基于知识库给出可追溯回答",
    prompt: "基于我的知识库回答这个问题，并给出引用来源：",
  },
  {
    icon: "code" as const,
    title: "排查问题",
    description: "分析日志、代码与运行异常",
    prompt: "帮我分析这个异常，定位最可能的原因，并给出可执行的排查步骤：",
  },
];

export function WorkspaceWelcome({
  onSelect,
}: {
  onSelect: (prompt: string) => void;
}) {
  return (
    <section className="workspace-welcome">
      <div className="welcome-orb" aria-hidden="true">
        <span>AM</span>
      </div>

      <div className="welcome-badge">
        <Icon name="sparkles" size={14} />
        <span>随时可以开始</span>
      </div>

      <h1>
        今天想让 AgentMesh
        <br />
        帮你完成什么？
      </h1>

      <p>
        描述你想完成的事情即可。AgentMesh 会在后台协调所需能力，
        你只需要关注过程中的关键确认与最终结果。
      </p>

      <div className="welcome-suggestions">
        {suggestions.map((item) => (
          <button
            className="welcome-suggestion"
            key={item.title}
            onClick={() => onSelect(item.prompt)}
            type="button"
          >
            <span className="welcome-suggestion-icon">
              <Icon name={item.icon} size={17} />
            </span>

            <span className="welcome-suggestion-copy">
              <strong>{item.title}</strong>
              <small>{item.description}</small>
            </span>

            <Icon name="arrow" size={15} />
          </button>
        ))}
      </div>
    </section>
  );
}
