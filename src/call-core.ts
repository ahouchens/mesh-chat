import { coreApiCallControl, coreApiCallMedia, coreApiSnapshot, ServiceCommandError } from "./api";
import { newOperationId } from "./operationId";
import type { CallMedia, CallSummary } from "./types";

export function callControl(action: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
  return coreApiCallControl(action, params, newOperationId());
}

export async function fetchCallMedia(call: Pick<CallSummary, "id" | "core_handle">): Promise<CallMedia> {
  const handle = call.core_handle ?? ((await coreApiSnapshot()) as { calls?: CallSummary[] })
    .calls?.find((item) => item.id === call.id)?.core_handle;
  if (!handle) throw new ServiceCommandError("call_not_found");
  const media = await coreApiCallMedia(handle);
  return { ...media, core_handle: handle } as unknown as CallMedia;
}
