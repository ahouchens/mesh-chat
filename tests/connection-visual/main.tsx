import React from "react";
import { createRoot } from "react-dom/client";
import { DirectConnectionSetup } from "../../src/DirectConnectionSetup";
import "../../src/styles.css";

// CI-only presentation fixture. Production components and styles, synthetic
// service state. This does not establish connectivity or test native lifecycle.
createRoot(document.getElementById("root")!).render(
  <div className="dialog-backdrop"><section className="dialog dialog--wide" role="dialog" aria-label="Join or connect">
    <div className="dialog__header"><h2>Join or connect</h2></div>
    <DirectConnectionSetup workspaceId="synthetic-workspace" />
  </section></div>
);
