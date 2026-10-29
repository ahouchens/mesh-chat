import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageContent } from "./MessageContent";
import { embedUrl, messageLinks, webUrl } from "./message-links";
import config from "../src-tauri/tauri.conf.json";

const native = vi.hoisted(() => ({ active: false, invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => native.active, invoke: native.invoke }));
afterEach(() => { cleanup(); vi.useRealTimers(); native.active = false; native.invoke.mockReset(); });

describe("message links", () => {
  it("preserves surrounding punctuation, balanced parentheses and line breaks", () => {
    const text = "Look (https://example.org/wiki/Thing_(name)).\nAlso www.example.com!";
    const links = messageLinks(text);
    expect(links.map((l) => l.label)).toEqual(["https://example.org/wiki/Thing_(name)", "www.example.com"]);
    render(<MessageContent text={text} />);
    expect(document.querySelector(".message-content__text")?.textContent).toBe(text);
    expect(screen.getByRole("link", { name: "www.example.com" }).getAttribute("href")).toBe("https://www.example.com/");
  });
  it("only links web URLs without credentials and leaves markup as text", () => {
    for (const value of ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "https://user:secret@example.com", "https://example.com/\nhi"]) expect(webUrl(value)).toBeNull();
    render(<MessageContent text={'<img src=x onerror=alert(1)> javascript:alert(1) https://user:secret@example.com'} />);
    expect(document.querySelectorAll("img, iframe, a")).toHaveLength(0);
  });
  it.each([
    "https://youtu.be/aqz-KE-bpKQ?t=1m30s", "https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=90",
    "https://m.youtube.com/shorts/aqz-KE-bpKQ?start=90", "https://youtube.com/live/aqz-KE-bpKQ?t=90",
  ])("recognizes video variants and preserves timestamps: %s", (url) => {
    const link = messageLinks(url)[0];
    expect(link.kind).toBe("youtube");
    expect(embedUrl(link, false)).toBe("https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ?playsinline=1&start=90");
  });
  it("does not embed lookalike hosts, credentials, invalid IDs or other ports", () => {
    for (const url of ["https://youtube.com.evil.test/watch?v=aqz-KE-bpKQ", "https://youtube.com:444/watch?v=aqz-KE-bpKQ", "https://youtu.be/bad", "https://x.com.evil.test/user/status/42"]) {
      expect(messageLinks(url)[0].kind).toBe("website");
    }
  });
  it("supports X and legacy Twitter posts without forwarding tracking parameters", () => {
    for (const url of ["https://x.com/NASA/status/123456?s=20", "https://twitter.com/i/web/status/123456", "https://mobile.twitter.com/NASA/status/123456/photo/1"]) {
      const link = messageLinks(url)[0];
      expect(link.kind).toBe("x");
      expect(embedUrl(link, true)).toBe("https://platform.twitter.com/embed/Tweet.html?id=123456&dnt=true&theme=dark&lang=en&hideThread=true");
    }
  });
});

describe("preview lifecycle", () => {
  it("allows only provider frames while keeping third-party scripts outside the app", () => {
    expect(config.app.security.csp).toContain("frame-src https://www.youtube-nocookie.com https://platform.twitter.com;");
    expect(config.app.security.csp).toContain("script-src 'self';");
    expect(config.app.security.csp).toContain("connect-src ipc: http://ipc.localhost;");
  });
  it("accepts bounded post sizes only from this provider frame and matching post", () => {
    render(<MessageContent text="https://x.com/jack/status/20" />);
    fireEvent.click(screen.getByRole("button", { name: "Load post" }));
    const frame = screen.getByTitle("X embedded post") as HTMLIFrameElement;
    const data = { "twttr.embed": { method: "twttr.private.resize", params: [{ height: 225, data: { tweet_id: "20" } }] } };
    const send = (origin: string, source: Window | null) => act(() => window.dispatchEvent(new MessageEvent("message", { origin, source, data })));
    send("https://evil.test", frame.contentWindow);
    send("https://platform.twitter.com", window);
    expect(frame.style.height).toBe("540px");
    send("https://platform.twitter.com", frame.contentWindow);
    expect(frame.style.height).toBe("225px");
    data["twttr.embed"].params[0].height = 1e9;
    send("https://platform.twitter.com", frame.contentWindow);
    expect(frame.style.height).toBe("1400px");
    data["twttr.embed"].params[0].data.tweet_id = "99";
    data["twttr.embed"].params[0].height = 300;
    send("https://platform.twitter.com", frame.contentWindow);
    expect(frame.style.height).toBe("1400px");
  });
  it("makes no remote requests until loaded, uses isolated frames, and closes playback", () => {
    render(<MessageContent text="https://youtu.be/aqz-KE-bpKQ" />);
    expect(document.querySelectorAll("iframe, img, script[src]")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Load video" }));
    const frame = screen.getByTitle("YouTube embedded video");
    expect(frame.getAttribute("src")).toContain("youtube-nocookie.com/embed/aqz-KE-bpKQ");
    expect(frame.getAttribute("sandbox")).not.toContain("allow-top-navigation");
    expect(frame.getAttribute("referrerpolicy")).toBe("strict-origin-when-cross-origin");
    expect(frame.getAttribute("allow")).not.toMatch(/camera|microphone/);
    fireEvent.click(screen.getByRole("button", { name: "Close YouTube preview" }));
    expect(document.querySelector("iframe")).toBeNull();
  });
  it("limits duplicate/large link lists but keeps all text links usable", () => {
    render(<MessageContent text={Array.from({ length: 10 }, (_, i) => `https://example.com/${i}`).join(" ")} />);
    expect(document.querySelectorAll(".link-preview")).toHaveLength(3);
    expect(document.querySelectorAll(".message-content__text a")).toHaveLength(10);
  });
  it("removes old embedded content when a message is edited", () => {
    const view = render(<MessageContent text="https://x.com/NASA/status/123" />);
    fireEvent.click(screen.getByRole("button", { name: "Load post" }));
    view.rerender(<MessageContent text="Removed the link" />);
    expect(document.querySelector("iframe")).toBeNull();
  });
  it("keeps an external fallback if a provider does not display content", () => {
    vi.useFakeTimers();
    render(<MessageContent text="https://youtu.be/aqz-KE-bpKQ" />);
    fireEvent.click(screen.getByRole("button", { name: "Load video" }));
    act(() => vi.advanceTimersByTime(12000));
    expect(screen.getByRole("status").textContent).toContain("unavailable or blocked");
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("href")).toBe("https://youtu.be/aqz-KE-bpKQ");
  });
  it("opens native links via the OS and reports failures without navigating chat", async () => {
    native.active = true;
    native.invoke.mockRejectedValueOnce(new Error("unavailable"));
    render(<MessageContent text="https://example.com" />);
    fireEvent.click(screen.getByRole("link", { name: "https://example.com" }));
    expect(native.invoke).toHaveBeenCalledWith("open_external_link", { url: "https://example.com/" });
    expect((await screen.findByRole("status")).textContent).toContain("Couldn’t open your browser");
  });
});
