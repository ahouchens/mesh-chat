import { coreApiCallMedia, coreApiProfile, coreApiRequest, coreApiSnapshot, ServiceCommandError } from "./api";
import { newOperationId } from "./operationId";
import type { CallMedia, CallSummary } from "./types";

export interface CallControlTicket {
  readonly key: string;
  readonly params: Readonly<Record<string, unknown> & { profile: string; action: string }>;
}

export async function prepareCallControl(action: string, params: Record<string, unknown>, scope?: string): Promise<CallControlTicket> {
  const profile = scope ?? (await coreApiProfile()).profile;
  return Object.freeze({ key: newOperationId(), params: Object.freeze({ ...structuredClone(params), profile, action }) });
}

export async function submitCallControl(ticket: CallControlTicket): Promise<Record<string, unknown>> {
  const response = await coreApiRequest<{ result: Record<string, unknown> }>("call.control", { ...ticket.params }, ticket.key);
  if (!response?.result || typeof response.result !== "object" || Array.isArray(response.result)) {
    throw new ServiceCommandError("core_api_protocol");
  }
  return response.result;
}

export async function incomingCallProfile(call: Pick<CallSummary, "id" | "core_handle">): Promise<string> {
  if (!call.core_handle) throw new ServiceCommandError("forbidden");
  const profile = (await coreApiProfile()).profile;
  const media = await coreApiCallMedia(call.core_handle, profile);
  if (media.id !== call.id) throw new ServiceCommandError("forbidden");
  return profile;
}

export async function fetchCallMedia(call: Pick<CallSummary, "id" | "core_handle">, scope?: string): Promise<CallMedia> {
  const handle = call.core_handle ?? ((await coreApiSnapshot()) as { calls?: CallSummary[] })
    .calls?.find((item) => item.id === call.id)?.core_handle;
  if (!handle) throw new ServiceCommandError("call_not_found");
  const media = await coreApiCallMedia(handle, scope);
  return { ...media, core_handle: handle } as unknown as CallMedia;
}
