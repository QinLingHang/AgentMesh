import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  resetKey: string;
};

type State = {
  failed: boolean;
};

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("AgentMesh panel render failed", error, info);
  }

  componentDidUpdate(previous: Props) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (!this.state.failed) {
      return this.props.children;
    }

    return (
      <section className="product-state product-state-error" role="alert">
        <strong>当前页面加载失败</strong>
        <p>页面组件出现异常。你可以切换到其他功能后再返回；如果问题持续，请查看浏览器控制台和 Run Details。</p>
      </section>
    );
  }
}

export function PanelLoading({ label = "正在加载页面…" }: { label?: string }) {
  return (
    <section className="product-state product-state-loading" aria-live="polite">
      <span className="product-spinner" aria-hidden="true" />
      <div>
        <strong>{label}</strong>
        <p>首次进入该模块时会按需加载资源。</p>
      </div>
    </section>
  );
}
