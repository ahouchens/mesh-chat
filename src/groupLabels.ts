import type { Contact, Group, GroupMember, GroupPostingPolicy } from "./types";

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function groupPolicyLabel(policy: GroupPostingPolicy): string {
  return policy === "owner_admins" ? "Only the owner can post" : "Everyone can post";
}

export function contactTrustLabel(contact: Contact): string {
  switch (contact.trust) {
    case "verified": return "Verified";
    case "approved": return "Approved";
    case "awaiting_consent": return "Waiting for acceptance";
    case "pending_request": return "Incoming request";
    case "identity_changed": return "Identity changed";
    case "blocked": return "Blocked";
  }
}

export function contactTrustDescription(contact: Contact): string {
  switch (contact.trust) {
    case "verified": return "You compared this fingerprint with the contact through another trusted channel.";
    case "approved": return "This contact accepted your connection, but the fingerprint has not been independently compared.";
    case "awaiting_consent": return "Your connection request is still waiting for this person to accept it.";
    case "pending_request": return "This person is waiting for you to accept or decline their request.";
    case "identity_changed": return "Messaging is paused because this destination presented different identity material.";
    case "blocked": return "Direct messages and connection requests from this contact are ignored.";
  }
}

export function groupInviteDeliveryLabel(member: GroupMember): string {
  switch (member.invite_delivery_state) {
    case "delivered": return "Invitation ready for review";
    case "received_by_endpoint": return "Reached device · confirming receipt";
    case "stored_for_delivery": return "Stored securely for delivery";
    case "sending": return "Sending invitation";
    case "waiting_for_keys": return "Trying to find device";
    case "expired": return "Invitation expired";
    case "failed": return "Invitation needs attention";
    default: return "Invitation queued";
  }
}

export function groupInvitationBanner(members: GroupMember[]): string {
  const awaiting = members.filter((member) => member.invite_delivery_state === "delivered");
  const confirming = members.filter((member) => member.invite_delivery_state === "received_by_endpoint");
  const unreachable = members.filter((member) => !["delivered", "received_by_endpoint", "stored_for_delivery"].includes(member.invite_delivery_state ?? "queued"));
  if (unreachable.length > 0) {
    const names = unreachable.map((member) => member.display_name).join(", ");
    return `Trying to reach ${names}. Keep Mesh Chat open on both devices and use the same non-guest network.`;
  }
  if (confirming.length > 0) return `${pluralize(confirming.length, "invitation")} reached the device and is waiting for app confirmation.`;
  if (awaiting.length > 0) return `${pluralize(awaiting.length, "invitation")} ready for review · waiting for acceptance.`;
  return `${pluralize(members.length, "invitation")} stored for delivery.`;
}

export function groupComposerState(group: Group, selfDestination: string): { canPost: boolean; reason: string } {
  const activeMembers = group.members.filter((member) => member.status === "active");
  const self = activeMembers.find((member) => member.destination_hash === selfDestination);
  const hasRecipient = activeMembers.some((member) => member.destination_hash !== selfDestination);
  const policyAllowsPosting = group.posting_policy === "members" || self?.role === "owner";
  const canPost = group.status === "active"
    && Boolean(self)
    && !group.membership_update_pending
    && hasRecipient
    && policyAllowsPosting;
  const reason = group.status === "closed"
    ? "This group is closed. Messages already received remain on this device."
    : group.status === "forked"
      ? "Messaging is paused because conflicting membership information was detected."
      : group.status === "joining"
        ? "Waiting for the owner to accept you and publish the next membership update."
        : group.status === "removed" || group.status === "left" || !self
          ? "You are no longer an active member of this group."
          : group.membership_update_pending
            ? "Messaging is paused until the signed membership update reaches every current member."
            : !hasRecipient
              ? "There are no other active members to receive a message."
              : !policyAllowsPosting
                ? "Only the owner can post in this announcement channel."
                : "";
  return { canPost, reason };
}

