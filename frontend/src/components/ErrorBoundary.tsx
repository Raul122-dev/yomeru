import { Component, type ReactNode } from "react";

/** Keeps one broken view from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: unknown }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: unknown }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="rounded-[var(--radius-md)] border border-[hsl(var(--danger)/.4)] bg-[hsl(var(--bg-surface))] p-5">
        <p className="eyebrow text-[hsl(var(--danger))]">This view crashed</p>
        <p className="mt-2 font-mono text-sm">{this.state.error.message}</p>
        <button
          className="mt-4 text-sm text-[hsl(var(--accent2))] underline underline-offset-4"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    );
  }
}
