export function errorMessage(error: unknown): string {
  const raw = String(error);
  if (raw.includes("direct_connection_unavailable")) {
    return "This device could not open a direct Internet path through the current network. Check whether the router permits UPnP, NAT-PMP, PCP, or inbound IPv6; otherwise use nearby access or explicitly choose an approved access point.";
  }
  if (raw.includes("profile_in_use")) {
    return "Your encrypted profile is still in use by another Mesh Chat process. Close any other Mesh Chat window, wait a moment, and reopen the app. Your existing encrypted data is unchanged.";
  }
  if (raw.includes("protected_storage_unavailable")) {
    return "Protected storage is unavailable. Turn on FileVault (macOS), use an EFS-capable NTFS profile (Windows), or place the profile on fscrypt/LUKS storage (Linux), then reopen Mesh Chat. No private data was written.";
  }
  if (raw.includes("credential_store_unavailable")) {
    return "The operating-system credential store is unavailable. Unlock Keychain, Credential Manager, or your Linux Secret Service, then reopen Mesh Chat.";
  }
  if (raw.includes("mobile_runtime_unavailable") || raw.includes("service_start_failed")) {
    return "The mobile messaging runtime could not start. Reopen Mesh Chat after unlocking the device and granting local-network access.";
  }
  if (raw.includes("service_timeout")) {
    return "Mesh Chat did not respond in time. Check the conversation before trying again.";
  }
  if (raw.includes("service_busy")) {
    return "Mesh Chat is finishing earlier delivery work. Wait a moment and try again.";
  }
  if (raw.includes("service_stopped") || raw.includes("service_not_running")) {
    return "The messaging service stopped. Reopen Mesh Chat and try again.";
  }
  if (raw.includes("native_unavailable")) {
    return "The on-device connection service stopped responding. Close and reopen Mesh Chat, then try again. Your saved request and messages are unchanged.";
  }
  if (raw.includes("workspace_already_known")) {
    return "This workspace is already saved on this device. Open it from the workspace switcher to check its status. A different invitation cannot replace an existing join request.";
  }
  if (raw.includes("identity_mismatch")) {
    return "This invitation’s identity check failed.";
  }
  if (raw.includes("invitation_expired")) {
    return "This invitation has expired. Ask the sender to create a new one.";
  }
  if (raw.includes("invitation_invalid")) {
    return "This does not appear to be a complete Mesh Chat invitation or connection document. Open the original Mesh Chat file or copy the entire value, including its prefix and everything after the colon.";
  }
  if (raw.includes("invitation_file_type_invalid")) {
    return "Choose a .meshchat-invite, .meshchat-connect, .meshchat-route, .meshchat, or JSON invitation file.";
  }
  if (raw.includes("invitation_file_too_large")) {
    return "That invitation file is larger than Mesh Chat can open safely.";
  }
  if (raw.includes("invitation_file_encoding_invalid")) {
    return "That invitation file is not valid UTF-8 text. Ask the sender to share the original Mesh Chat file again.";
  }
  if (raw.includes("invitation_file_invalid")) {
    return "That file does not contain a complete Mesh Chat invitation or connection document.";
  }
  if (raw.includes("invitation_file_unavailable")) {
    return "Android could not read that file. Download it to this device and try again.";
  }
  if (raw.includes("contact_not_approved")) {
    return "This contact is not approved for that action.";
  }
  if (raw.includes("contact_in_use")) {
    return "Remove this contact from any pending group invitations before deleting them.";
  }
  if (raw.includes("stale_cursor")) {
    return "History changed while this page was open. Reload from the newest retained page.";
  }
  if (raw.includes("history_pruned")) {
    return "That history was pruned from this device under the active retention preference.";
  }
  if (raw.includes("workspace_limit_reached")) {
    return "This device already has 16 workspaces. Remove a workspace you have left or closed before joining another.";
  }
  if (raw.includes("invalid_request")) {
    return "That information could not be validated.";
  }
  return "Something went wrong. Your saved messages were not discarded.";
}

