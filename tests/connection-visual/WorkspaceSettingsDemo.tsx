import { useState } from "react";
import { WorkspaceSettingsPage, type WorkspaceSettingsSection } from "../../src/WorkspaceSettingsPage";
import { WorkspacePeopleSettingsContent, WorkspaceGeneralSettingsContent, WorkspaceHistorySettingsContent, WorkspaceDevicesSettingsContent, WorkspaceAuthoritySettingsContent, WorkspaceAccessSettingsContent } from "../../src/App";
import type { Workspace, NetworkSettings } from "../../src/types";

const noop = () => undefined;
const workspace: Workspace = {
  id: "workspace-demo", name: "Direct Test", description: "Our shared space for ideas, plans and conversations.", state: "active", local_role: "owner",
  local_member_id: "alex", local_device_id: "alex-device", owner_member_id: "alex", authority_device_id: "alex-device", epoch: 1,
  manifest_hash: "demo", genesis_digest: "demo", general_channel_id: "general", channel_discovery: "converged", retention_days: 90,
  policies: { channel_creation: "all_members", posting: "all_members", invitation_requests: "owner_and_admins" },
  members: [
    { id: "alex", display_name: "Alex", role: "owner", status: "active", short_id: "6a18ef", device: { id: "alex-device", destination_hash: "demo-alex", fingerprint: "DEMO" } },
    { id: "jamie", display_name: "Jamie", role: "member", status: "active", short_id: "b2c485", device: { id: "jamie-device", destination_hash: "demo-jamie", fingerprint: "DEMO" } },
    { id: "sam", display_name: "Sam", role: "admin", status: "active", short_id: "cf36a2", device: { id: "sam-device", destination_hash: "demo-sam", fingerprint: "DEMO" } },
  ], authorization_generation: 1, retention_generation: 1, mention_unread_count: 0, thread_unread_count: 0, created_at: 1, updated_at: 1,
};

// Production panels, synthetic members and read-only service responses.
export function WorkspaceSettingsDemo() {
  const [section, setSection] = useState<WorkspaceSettingsSection>("general");
  const common = { workspace, busy: false, error: "" };
  const general = { ...common, conversation: null, networkSettings: { approved_propagation_nodes: [] } as unknown as NetworkSettings, reconnect: null,
    onOpenAccess: () => setSection("access"), onUpdateMetadata: noop, onUpdatePolicies: noop, onSetNotificationPreference: noop,
    onApprovePropagationNode: noop, onCloseWorkspace: noop, onLeave: noop, onRemove: noop };
  return <main className="app-shell app-shell--settings workspace-demo">
    <aside className="sidebar" aria-hidden="true"><div style={{ padding: 24 }}><h2>Mesh Chat</h2><p>Direct Test</p><hr /><p># general</p><p># ideas</p><p>People</p><p>Workspace settings</p></div></aside>
    <div className="main-pane" />
    <div className="settings-page-slot workspace-settings-slot">
      <WorkspaceSettingsPage name={workspace.name} role={workspace.local_role} section={section} busy={false} onSelect={setSection} onClose={() => setSection("general")} panels={{
        general: <WorkspaceGeneralSettingsContent {...general} />,
        connections: <WorkspaceGeneralSettingsContent {...general} view="connections" />,
        people: <WorkspacePeopleSettingsContent {...common} requests={[]} adminRequests={[]} onRequestName={noop} onDecideName={noop} onRemove={noop} onChangeRole={noop} onInvitationPolicy={noop} onSubmitAdminRequest={noop} onDecideAdminRequest={noop} onCancelAdminRequest={noop} onDismissAdminRequest={noop} onMessage={noop} />,
        history: <WorkspaceHistorySettingsContent {...common} conversationId="general" conversationName="general" onUpdate={noop} onPrune={async () => null} />,
        devices: <WorkspaceDevicesSettingsContent {...common} transitions={[]} onCreate={async () => null} onDecide={noop} onRemove={noop} onReadSync={noop} />,
        authority: <WorkspaceAuthoritySettingsContent {...common} transitions={[]} onOffer={noop} onAccept={noop} onFinalize={noop} onReportLoss={noop} />,
        access: <WorkspaceAccessSettingsContent workspace={workspace} onSaved={async () => undefined} />,
      }} />
    </div>
  </main>;
}
