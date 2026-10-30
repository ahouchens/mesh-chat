import { serviceCommand } from "./api";
import type { MessageLink } from "./message-links";

export type PreviewCard = { status: "ready"; title: string; author: string; text: string; image: string | null };
type PreviewResult = PreviewCard | { status: "loading" | "unavailable" };

// Only called after consent. Fetching runs in a bounded native worker, outside
// the service command lock. Polls stop on unmount, edits, close, or timeout.
export async function loadPreview(link: MessageLink, signal: AbortSignal): Promise<PreviewCard | null> {
  const deadline = Date.now() + 15000;
  while (!signal.aborted && Date.now() < deadline) {
    const result = await serviceCommand<PreviewResult>("link_preview", {
      provider: link.kind, identifier: link.id,
    });
    if (signal.aborted) return null;
    if (result.status === "ready") return result;
    if (result.status !== "loading") return null;
    await new Promise<void>((resolve) => {
      const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
      const timer = setTimeout(finish, 500);
      signal.addEventListener("abort", finish, { once: true });
    });
  }
  return null;
}
