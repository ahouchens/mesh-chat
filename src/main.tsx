import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import RuntimeErrorBoundary from "./RuntimeErrorBoundary";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RuntimeErrorBoundary>
      <App />
    </RuntimeErrorBoundary>
  </React.StrictMode>,
);
