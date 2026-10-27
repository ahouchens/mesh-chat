import { beginCallAudio, endCallAudio } from "./api";

let owner: object | null = null;
let pending: Promise<unknown> = Promise.resolve();

function serialize<T>(operation: () => Promise<T>): Promise<T> {
  const result = pending.then(operation);
  pending = result.catch(() => undefined);
  return result;
}

/** Serialize Android's process-wide audio focus across call dialogs. */
export function acquireCallAudio(token: object, media: "audio" | "video"): Promise<{ granted: boolean }> {
  return serialize(async () => {
    const result = await beginCallAudio(media);
    if (result.granted) owner = token;
    return result;
  });
}

/** A late cleanup from an older call cannot release a newer call's focus. */
export function releaseCallAudio(token: object): Promise<void> {
  return serialize(async () => {
    if (owner !== token) return;
    owner = null;
    await endCallAudio();
  });
}
