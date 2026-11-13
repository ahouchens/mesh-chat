import type { DirectDoctorReport, DirectDoctorStep } from "./types";

export const directPhaseLabel: Record<DirectDoctorStep["phase"], string> = {
  precondition: "Internet route", ipv6: "Native IPv6", upnp: "UPnP",
  nat_pmp: "NAT-PMP", pcp: "PCP", firewall: "Host firewall",
  listener: "Invitation listener",
};

export function directReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    ready_to_prepare: "Ready to prepare",
    no_default_route: "No active default Internet route",
    no_global_ipv4: "No directly assigned public IPv4",
    no_global_ipv6: "No usable global IPv6 on the active route",
    upnp_no_discovery: "No UPnP Internet gateway discovered",
    upnp_wan_private: "Upstream or double NAT detected",
    upnp_wan_shared: "Provider/shared NAT likely",
    upnp_mapping_denied: "The router denied the UPnP mapping",
    upnp_unsupported_lease: "The router does not support the requested UPnP lease",
    nat_pmp_no_response: "No NAT-PMP response",
    nat_pmp_mapping_denied: "The router denied the NAT-PMP mapping",
    pcp_no_response: "No PCP response",
    pcp_mapping_denied: "The router denied the PCP mapping",
    upstream_nat_detected: "Upstream or double NAT detected",
    listener_bind_failed: "The temporary listener could not start",
    windows_firewall_blocked: "Windows Firewall needs attention",
    windows_firewall_permission_required: "Permission will be requested after preparing",
    firewall_check_unsupported: "Check this device’s firewall manually",
    session_limit: "Too many temporary invitations are active",
    direct_public_ipv4: "Public IPv4 is assigned directly to this device",
    global_ipv6_available: "Usable global IPv6 is present",
    mapping_prepared: "Prepared, not externally verified",
    router_state_changed: "The router or address changed; create a new invitation",
    manual_setup_required: "Automatic setup is unavailable",
  };
  return labels[reason] ?? "Unavailable on this network";
}

export function directActionLabel(action: string): string {
  const labels: Record<string, string> = {
    retry: "Retry after checking this network.",
    continue: "Continue to the remaining checks.",
    prepare_direct: "Prepare the invitation, then keep Mesh Chat open.",
    share_invitation: "Share the invitation and keep Mesh Chat open.",
    wait_for_recipient: "Keep Mesh Chat open while the recipient connects.",
    configure_firewall_after_prepare: "After preparing, allow only its temporary TCP port.",
    connect_to_internet: "Connect this device to the Internet and retry.",
    try_router_mapping: "Try a supported automatic router mapping or manual forward.",
    try_another_method: "Try another listed mapping method or manual forwarding.",
    check_host_firewall: "Check this device’s inbound firewall for the temporary TCP port.",
    configure_upstream_router_or_bridge_mode: "Forward through both routers or use modem bridge/passthrough mode.",
    contact_provider_or_use_approved_access_point: "Ask the provider about inbound service or choose an approved participant access point.",
    set_up_manual_forward_or_choose_explicit_fallback: "Set up a manual TCP forward, choose same-network mode, or explicitly select an approved access point.",
    stop_an_active_invitation: "Stop an older hosted invitation and retry.",
    check_active_network_profile: "Connect using the intended Windows network profile and retry.",
    retry_or_check_firewall: "Retry, then check the host firewall if binding still fails.",
    restart_app: "Restart Mesh Chat and try again.",
    follow_guided_firewall_instructions: "Use the guided narrow firewall rule or configure it manually.",
    use_ipv6_firewall_instructions: "Allow only the temporary TCP port in the IPv6 firewall, then retry.",
  };
  return labels[action] ?? "Retry after checking this network.";
}

export function sanitizedDoctorSummary(report: DirectDoctorReport): string {
  return [
    `Mesh Chat direct connection: ${directReasonLabel(report.summary.reason)}`,
    ...report.checks.map((step) => `${directPhaseLabel[step.phase]}: ${step.result} — ${directReasonLabel(step.reason)}`),
    `Next action: ${directActionLabel(report.summary.recommended_action)}`,
  ].join("\n");
}

export function canPrepareDirectHost(report: DirectDoctorReport): boolean {
  return report.summary.result === "available"
    || report.summary.result === "prepared_unverified";
}

export function directFailureReport(reason: unknown): DirectDoctorReport | null {
  const details = (reason as { details?: Record<string, string> })?.details;
  if (!details?.phase || !details.result || !details.reason || !details.recommended_action) return null;
  const step = details as unknown as DirectDoctorStep;
  return { summary: step, checks: [step] };
}
