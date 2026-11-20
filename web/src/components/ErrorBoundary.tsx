/**
 * 根级错误边界：渲染异常时显示可读的错误页，而不是整片空白。
 * React 的错误边界必须是 class 组件；这里只提供最小的恢复入口（刷新页面）。
 */
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 保留控制台堆栈，便于用户反馈问题时复制。
    console.error("Unhandled UI error", error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 p-6 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <div className="w-full max-w-lg rounded-2xl border border-red-200 bg-white p-6 shadow-xl dark:border-red-500/30 dark:bg-zinc-900">
          <h1 className="text-base font-semibold">页面出现错误</h1>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            界面渲染时发生异常，你的数据不会丢失。可以刷新页面恢复；如果反复出现，请把下面的信息反馈给开发者。
          </p>
          <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-zinc-100 p-3 text-[11px] text-red-700 dark:bg-black/40 dark:text-red-300">
            {error.message}
          </pre>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400"
            >
              刷新页面
            </button>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded-lg border border-zinc-200 px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }
}
