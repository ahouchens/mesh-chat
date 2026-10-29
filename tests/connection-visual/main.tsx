import React from "react";
import { createRoot } from "react-dom/client";
import { DirectConnectionSetup } from "../../src/DirectConnectionSetup";
import { ContactRequests } from "../../src/ContactRequests";
import "../../src/styles.css";
import { LinkPreviewDemo } from "./LinkPreviewDemo";
import { WorkspaceSettingsDemo } from "./WorkspaceSettingsDemo";

// CI-only presentation fixture. Production components and styles, synthetic
// service state. This does not establish connectivity or test native lifecycle.
const inbox = new URLSearchParams(location.search).has("contact-requests");
createRoot(document.getElementById("root")!).render(new URLSearchParams(location.search).has("workspace-settings") ? <WorkspaceSettingsDemo /> : new URLSearchParams(location.search).has("links") ? <LinkPreviewDemo /> : inbox ?
  <div className="dialog-backdrop"><section className="dialog" role="dialog" aria-label="Contact requests">
    <div className="dialog__header"><h2>Contact requests</h2></div>
    <ContactRequests invitations={[{
      id: "synthetic", state: "pending", received_at: 1, expires_at: 4_000_000_000,
      expired: false, native_connected: false,
      preview: { display_name: "Taylor’s phone", destination_hash: "synthetic", identity_hash: "synthetic", fingerprint: "ABCD EFGH IJKL MNOP QRST UVWX YZAB CDEF", hints: [], expires_at: 4_000_000_000 },
      workspace: { workspace_id: "synthetic", name: "Family and friends", description: "", owner_fingerprint: "ABCD", member_count: 2, retention_days: 30, expires_at: 4_000_000_000 },
    }]} approvals={[]} waiting={[]} busy={false} error="" connectedPeers={[]} onInvitation={() => undefined} onApproval={() => undefined} />
  </section></div> :
  <div className="dialog-backdrop"><section className="dialog dialog--wide" role="dialog" aria-label="Join or connect">
    <div className="dialog__header"><h2>Join or connect</h2></div>
    <DirectConnectionSetup workspaceId="synthetic-workspace" />
  </section></div>
);
