import { coreApiCapabilities, coreApiRequest, coreApiSnapshot, coreApiUnlockCredential, initializeNativeService, initializeService, ServiceCommandError } from "./api";
import type { Snapshot } from "./types";

const OPERATIONS = ["profile.catalog", "profile.lock", "profile.select", "profile.unlock"];
const LIMITS = ["profile_slots", "profile_lifecycle_keys_per_host", "profile_lifecycle_keys_per_caller_profile", "profile_unlock_credentials"];
const handle = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export const profileErrorCode = (reason: unknown): string => reason && typeof reason === "object" && "code" in reason
  ? String(reason.code) : reason instanceof Error ? reason.message : String(reason);
export interface ProfileCatalog {
  profiles: Array<{ profile: string; display_name: string; selected: boolean; state: "locked" | "unlocked" | "retiring" }>;
  selected_profile: string | null;
  revision: number;
}
export interface ProfileAction {
  readonly action: "lock" | "select" | "unlock";
  readonly profile: string;
  readonly key: string;
}
export interface ProfileUnlockCredential {
  readonly credential_handle: string;
  readonly expires_in_ms: number;
  readonly revision: number;
  readonly host_generation: string;
}
export function parseProfileCatalog(value: unknown): ProfileCatalog {
  const catalog = value as ProfileCatalog;
  if (!catalog || !Number.isSafeInteger(catalog.revision) || catalog.revision < 0 || !Array.isArray(catalog.profiles)
      || catalog.profiles.length > 8 || !(catalog.selected_profile === null || handle(catalog.selected_profile))) throw new ServiceCommandError("core_api_protocol");
  const seen = new Set<string>();
  for (const row of catalog.profiles) {
    if (!row || !handle(row.profile) || seen.has(row.profile) || typeof row.display_name !== "string" || typeof row.selected !== "boolean"
        || !["locked", "unlocked", "retiring"].includes(row.state) || row.selected !== (row.profile === catalog.selected_profile)
        || (!row.selected && row.state !== "locked")) throw new ServiceCommandError("core_api_protocol");
    seen.add(row.profile);
  }
  if (catalog.selected_profile !== null && !seen.has(catalog.selected_profile)) throw new ServiceCommandError("core_api_protocol");
  return catalog;
}
export async function supportsProfileLifecycle(): Promise<boolean> {
  const caps = await coreApiCapabilities();
  if (!OPERATIONS.some((operation) => caps.operations?.includes(operation))) return false;
  if (caps.api_major !== 1 || !Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1
      || !OPERATIONS.every((operation) => caps.operations?.includes(operation))
      || !LIMITS.every((name) => Number.isSafeInteger(caps.limits?.[name]) && caps.limits![name] > 0)) throw new ServiceCommandError("core_api_protocol");
  return true;
}
export async function queryProfileCatalog(): Promise<ProfileCatalog> {
  return parseProfileCatalog(await coreApiRequest("profile.catalog"));
}
export async function authenticateProfile(profile: string): Promise<ProfileUnlockCredential> {
  if (!handle(profile)) throw new ServiceCommandError("invalid_request");
  const credential = await coreApiUnlockCredential(profile) as { credential_handle?: unknown; expires_in_ms?: unknown; revision?: unknown; host_generation?: unknown };
  if (!credential || !handle(credential.credential_handle) || !Number.isSafeInteger(credential.expires_in_ms) || Number(credential.expires_in_ms) <= 0
      || !Number.isSafeInteger(credential.revision) || Number(credential.revision) < 0
      || typeof credential.host_generation !== "string" || !/^[a-f0-9]{32}$/.test(credential.host_generation)) throw new ServiceCommandError("core_api_protocol");
  return Object.freeze(credential as ProfileUnlockCredential);
}
/** Keys and target stay with the UI owner; refreshed authorization never changes logical identity. */
export async function submitProfileAction(ticket: ProfileAction, credential?: string): Promise<ProfileCatalog> {
  if (!handle(ticket.profile) || !/^[\x21-\x7e]{16,128}$/.test(ticket.key) || (ticket.action === "unlock" && !handle(credential))) throw new ServiceCommandError("invalid_request");
  const result = parseProfileCatalog(await coreApiRequest(`profile.${ticket.action}`, {
    profile: ticket.profile, ...(ticket.action === "unlock" ? { credential_handle: credential } : {}),
  }, ticket.key));
  const selected = result.profiles.find((row) => row.selected);
  if (selected?.state !== "retiring" && (selected?.profile !== ticket.profile
      || (ticket.action === "unlock" && selected.state !== "unlocked")
      || (ticket.action === "lock" && selected.state !== "locked"))) throw new ServiceCommandError("core_api_protocol");
  return result;
}
export async function snapshotForCatalog(catalog: ProfileCatalog): Promise<Snapshot> {
  const selected = catalog.profiles.find((row) => row.selected);
  if (!selected || selected.state !== "unlocked") throw new ServiceCommandError("locked");
  const snapshot = await coreApiSnapshot() as unknown as Snapshot;
  const after = await queryProfileCatalog();
  if (after.revision !== catalog.revision || after.selected_profile !== catalog.selected_profile
      || after.profiles.find((row) => row.selected)?.state !== "unlocked") throw new ServiceCommandError("resync_required");
  return snapshot;
}
export async function bootProfiles(): Promise<{ catalog: ProfileCatalog | null; snapshot: Snapshot | null; error?: unknown }> {
  let runtime = false;
  try { runtime = await supportsProfileLifecycle(); }
  catch (reason) { if (!["core_api_unavailable", "unavailable", "unsupported_operation"].includes(profileErrorCode(reason))) throw reason; }
  let legacy: Snapshot | null = null;
  if (runtime) {
    try { await initializeNativeService(); } catch (reason) { if (profileErrorCode(reason) !== "locked") throw reason; }
  } else {
    let locked = false;
    try { legacy = await initializeService(); } catch (reason) { if (profileErrorCode(reason) !== "locked") throw reason; locked = true; }
    try { runtime = await supportsProfileLifecycle(); }
    catch (reason) { if (!["core_api_unavailable", "unsupported_operation"].includes(profileErrorCode(reason))) throw reason; }
    if (!runtime && locked) throw new ServiceCommandError("locked");
  }
  if (!runtime) return { catalog: null, snapshot: legacy };
  const catalog = await queryProfileCatalog();
  try { return { catalog, snapshot: catalog.profiles.find((row) => row.selected)?.state === "unlocked" ? await snapshotForCatalog(catalog) : null }; }
  catch (error) { return { catalog, snapshot: null, error }; }
}
