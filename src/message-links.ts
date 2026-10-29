export type MessageLink = { href: string; label: string; start: number; end: number; host: string;
  kind: "youtube" | "x" | "website"; id?: string; startSeconds?: number };

export function webUrl(value: string): URL | null {
  if (value.length > 4096 || /[\u0000-\u0020\u007f]/.test(value)) return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && url.hostname && !url.username && !url.password ? url : null;
  } catch { return null; }
}

function startTime(value: string | null): number | undefined {
  if (!value) return;
  const match = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(value);
  const seconds = /^\d+$/.test(value) ? Number(value) : match
    ? Number(match[1] ?? 0) * 3600 + Number(match[2] ?? 0) * 60 + Number(match[3] ?? 0) : 0;
  return seconds > 0 && seconds <= 604800 ? seconds : undefined;
}

export function messageLinks(text: string): MessageLink[] {
  const result: MessageLink[] = [];
  for (const match of text.matchAll(/(?:https?:\/\/|www\.)[^\s<>"'`]+/gi)) {
    if (match.index > 0 && /[\w@/]/.test(text[match.index - 1])) continue;
    let label = match[0].replace(/[.,!?;:]+$/, "");
    for (const [open, close] of [["(", ")"], ["[", "]"], ["{", "}"]]) {
      while (label.endsWith(close) && label.split(close).length > label.split(open).length) label = label.slice(0, -1);
    }
    const url = webUrl(/^www\./i.test(label) ? `https://${label}` : label);
    if (!url) continue;
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    const link: MessageLink = { href: url.href, label, start: match.index, end: match.index + label.length, host, kind: "website" };
    const parts = url.pathname.split("/").filter(Boolean);
    const youtube = ["youtube.com", "m.youtube.com", "youtube-nocookie.com"].includes(host);
    const id = host === "youtu.be" ? parts[0] : youtube
      ? parts[0] === "watch" ? url.searchParams.get("v") : ["shorts", "embed", "live"].includes(parts[0]) ? parts[1] : null : null;
    if (id && /^[A-Za-z0-9_-]{11}$/.test(id) && !url.port) {
      Object.assign(link, { kind: "youtube", id, startSeconds: startTime(url.searchParams.get("t") ?? url.searchParams.get("start")) });
    } else if (["x.com", "twitter.com", "mobile.twitter.com", "m.twitter.com"].includes(host) && !url.port) {
      const post = /^\/(?:[A-Za-z0-9_]{1,15}\/status|i\/web\/status)\/(\d{1,20})(?:\/(?:photo|video)\/\d+)?\/?$/.exec(url.pathname);
      if (post) Object.assign(link, { kind: "x", id: post[1] });
    }
    result.push(link);
  }
  return result;
}

// Only provider-owned frames; message text can never choose an iframe origin.
export function embedUrl(link: MessageLink, dark: boolean): string | null {
  if (link.kind === "youtube" && /^[A-Za-z0-9_-]{11}$/.test(link.id ?? "")) {
    const url = new URL(`https://www.youtube-nocookie.com/embed/${link.id}`);
    url.searchParams.set("playsinline", "1");
    if (link.startSeconds) url.searchParams.set("start", String(link.startSeconds));
    return url.href;
  }
  if (link.kind === "x" && /^\d{1,20}$/.test(link.id ?? "")) {
    const url = new URL("https://platform.twitter.com/embed/Tweet.html");
    url.search = new URLSearchParams({ id: link.id!, dnt: "true", theme: dark ? "dark" : "light", lang: "en", hideThread: "true" }).toString();
    return url.href;
  }
  return null;
}
