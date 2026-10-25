import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ContactRequests } from "./ContactRequests";
import type { ContactInvitation } from "./types";

afterEach(cleanup);

const invitation: ContactInvitation = {
  id: "saved", state: "pending", received_at: 1, expires_at: 4_000_000_000,
  expired: false, native_connected: false, workspace: null,
  preview: { display_name: "Taylor", destination_hash: "peer", identity_hash: "identity", fingerprint: "ABCD EFGH", hints: [], expires_at: 4_000_000_000 },
};

it("keeps offline acceptance explicit and shows how to deliver the request", () => {
  const onInvitation = vi.fn();
  render(<ContactRequests invitations={[invitation]} approvals={[]} waiting={[]} busy={false} error="" connectedPeers={[]} onInvitation={onInvitation} onApproval={vi.fn()} />);
  expect(screen.getByText(/connection is no longer active/)).toBeTruthy();
  expect(onInvitation).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Accept contact" }));
  expect(onInvitation).toHaveBeenCalledWith(invitation, true);
});

it("explains expiry and offers dismissal without acceptance", () => {
  const onInvitation = vi.fn();
  const expired = { ...invitation, expired: true };
  render(<ContactRequests invitations={[expired]} approvals={[]} waiting={[]} busy={false} error="" connectedPeers={[]} onInvitation={onInvitation} onApproval={vi.fn()} />);
  expect((screen.getByRole("button", { name: "Accept contact" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(onInvitation).toHaveBeenCalledWith(expired, false);
});

it("includes the workspace in the explicit consent action", () => {
  render(<ContactRequests invitations={[{ ...invitation, native_connected: true, workspace: { workspace_id: "workspace", name: "Family", description: "", owner_fingerprint: "ABCD", member_count: 1, retention_days: 7, expires_at: 4_000_000_000 } }]} approvals={[]} waiting={[]} busy={false} error="" connectedPeers={[]} onInvitation={vi.fn()} onApproval={vi.fn()} />);
  expect(screen.getByText("Family")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Accept contact and request to join" })).toBeTruthy();
  expect(screen.getByText(/WebRTC is connected/)).toBeTruthy();
});
