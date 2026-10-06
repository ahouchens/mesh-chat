import { Component, type ErrorInfo, type ReactNode } from "react";

interface RuntimeErrorBoundaryProps {
  children: ReactNode;
}

interface RuntimeErrorBoundaryState {
  failed: boolean;
}

export default class RuntimeErrorBoundary extends Component<RuntimeErrorBoundaryProps, RuntimeErrorBoundaryState> {
  state: RuntimeErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): RuntimeErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown, details: ErrorInfo): void {
    console.error("Mesh Chat interface error", error, details.componentStack);
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="fatal-screen" role="alert">
        <h1>Mesh Chat needs to reload</h1>
        <p>Your profile, contacts, and saved messages are safe.</p>
        <button className="button button--primary" type="button" onClick={() => window.location.reload()}>
          Reload Mesh Chat
        </button>
      </main>
    );
  }
}
