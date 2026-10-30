import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { ExternalLink, Globe2, Play, ShieldCheck, X } from "lucide-react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { embedUrl, messageLinks, type MessageLink } from "./message-links";
import { loadPreview, type PreviewCard } from "./link-preview";
import "./MessageContent.css";

function WebLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  const [failed, setFailed] = useState(false);
  async function open(event: MouseEvent<HTMLAnchorElement>) {
    if (!isTauri()) return;
    event.preventDefault();
    try { await invoke("open_external_link", { url: href }); setFailed(false); }
    catch { setFailed(true); }
  }
  return <><a className={className} href={href} target="_blank" rel="noopener noreferrer" onClick={open}>{children}</a>
    {failed && <small className="link-open-error" role="status">Couldn’t open your browser. Copy the link to open it.</small>}</>;
}

function LinkPreview({ link }: { link: MessageLink }) {
  const [loaded, setLoaded] = useState(false);
  const [embedded, setEmbedded] = useState(false);
  const [card, setCard] = useState<PreviewCard | null>(null);
  const [cardState, setCardState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [slow, setSlow] = useState(false);
  const [postHeight, setPostHeight] = useState(540);
  const [postReady, setPostReady] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [dark, setDark] = useState(document.documentElement.dataset.theme === "dark");
  useEffect(() => {
    if (!loaded) return;
    const controller = new AbortController();
    setCardState("loading");
    void loadPreview(link, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setCard(result);
      setCardState(result ? "ready" : "unavailable");
    }).catch(() => { if (!controller.signal.aborted) setCardState("unavailable"); });
    return () => controller.abort();
  }, [loaded, link.kind, link.id]);
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(document.documentElement.dataset.theme === "dark"));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!embedded || postReady) return;
    // A frame's load event does not establish that a post/video is available.
    const timer = window.setTimeout(() => setSlow(true), 12000);
    return () => window.clearTimeout(timer);
  }, [embedded, postReady]);
  useEffect(() => {
    if (!embedded || link.kind !== "x") return;
    function resize(event: MessageEvent) {
      if (event.origin !== "https://platform.twitter.com" || event.source !== frameRef.current?.contentWindow) return;
      const payload = event.data?.["twttr.embed"];
      const params = payload?.params?.[0];
      if (params?.data?.tweet_id !== link.id) return;
      if (payload?.method === "twttr.private.resize" && typeof params.height === "number" && Number.isFinite(params.height)) {
        setPostHeight(Math.min(1400, Math.max(200, Math.ceil(params.height))));
      }
      if (payload?.method === "twttr.private.rendered") { setPostReady(true); setSlow(false); }
    }
    window.addEventListener("message", resize);
    return () => window.removeEventListener("message", resize);
  }, [embedded, link.kind, link.id]);
  const provider = link.kind === "youtube" ? "YouTube" : link.kind === "x" ? "X" : link.host;
  const title = card?.title || (link.kind === "youtube" ? "YouTube video" : link.kind === "x" ? "Post on X" : link.host);
  const frame = embedUrl(link, dark);
  return <section className={`link-preview link-preview--${link.kind}`} aria-label={`${provider} link preview`}>
    <div className="link-preview__bar"><span className={`link-preview__brand link-preview__brand--${link.kind}`}>
      {link.kind === "youtube" ? <Play size={13} fill="currentColor" /> : link.kind === "x" ? <span aria-hidden="true">𝕏</span> : <Globe2 size={16} />}
    </span><strong>{provider}</strong><WebLink href={link.href} className="link-preview__external">Open <ExternalLink size={13} /></WebLink>
    {loaded && <button className="link-preview__close" type="button" aria-label={`Close ${provider} preview`} onClick={() => { setLoaded(false); setEmbedded(false); setCard(null); setCardState("idle"); setSlow(false); setPostReady(false); }}><X size={16} /></button>}</div>
    <div className="link-preview__body">
      {card?.image && /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(card.image) ? <img className="link-preview__thumbnail" src={card.image} alt="Video thumbnail" /> :
        frame && !card && <div className={`link-preview__art link-preview__art--${link.kind}`} aria-hidden="true">{link.kind === "youtube" ? <Play size={30} fill="currentColor" /> : <span>𝕏</span>}<span>{link.kind === "youtube" ? "VIDEO" : "POST"}</span></div>}
      <div className="link-preview__copy"><h4>{title}</h4>
        {card?.author && <div className="link-preview__author">{card.author}</div>}
        <p>{card?.text || (link.kind === "youtube" ? "Watch on YouTube, or try playing here." : link.kind === "x" ? "Preview the post here, or open it on X." : `${new URL(link.href).pathname}${new URL(link.href).search}`)}</p>
      </div>
      {frame && !loaded && <><button type="button" className="link-preview__load" onClick={() => setLoaded(true)}>Load preview</button>
        <small className="link-preview__privacy"><ShieldCheck size={13} />Connects to {provider} when you load it.</small></>}
      {loaded && cardState === "loading" && <p className="link-preview__note" role="status">Loading preview…</p>}
      {loaded && cardState === "unavailable" && <p className="link-preview__note" role="status">Preview unavailable. You can still open this link on {provider}.</p>}
      {loaded && frame && !embedded && <button type="button" className="link-preview__load" onClick={() => { setEmbedded(true); setSlow(false); setPostReady(false); }}>{link.kind === "youtube" ? <Play size={16} /> : <ExternalLink size={16} />}{link.kind === "youtube" ? "Try playing here" : "Try interactive post"}</button>}
      {embedded && <button type="button" className="link-preview__load" onClick={() => setEmbedded(false)}>Hide {link.kind === "youtube" ? "player" : "interactive post"}</button>}
    </div>
    {embedded && frame && <>
      <iframe ref={frameRef} style={link.kind === "x" ? { height: postHeight } : undefined} className={`link-preview__frame link-preview__frame--${link.kind}`} src={frame} title={`${provider} embedded ${link.kind === "youtube" ? "video" : "post"}`}
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-presentation"
        allow="encrypted-media; fullscreen; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin"
        onError={() => setSlow(true)} />
      <div className="link-preview__note" role="status">{slow ? `Not displaying? This content may be unavailable or blocked. Use Open to view it on ${provider}.` : `Content provided directly by ${provider}.`}</div>
    </>}
  </section>;
}

export function MessageContent({ text }: { text: string }) {
  const links = useMemo(() => messageLinks(text), [text]);
  const pieces: ReactNode[] = [];
  let cursor = 0;
  for (const link of links) {
    pieces.push(text.slice(cursor, link.start), <WebLink key={link.start} href={link.href}>{link.label}</WebLink>);
    cursor = link.end;
  }
  pieces.push(text.slice(cursor));
  const unique = [...new Map(links.map((link) => [link.kind === "website" ? link.href : `${link.kind}:${link.id}:${link.startSeconds ?? 0}`, link])).values()].slice(0, 3);
  return <div className="message-content"><p className="message-content__text">{pieces}</p>
    {unique.length > 0 && <div className="message-content__previews">{unique.map((link) => <LinkPreview key={link.href} link={link} />)}</div>}
  </div>;
}
