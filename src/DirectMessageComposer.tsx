import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Send } from "lucide-react";
import { openCoreComposer } from "./core-composer";
import { DirectComposerController } from "./direct-composer";
import { ProfileRetiredError, useProfileLifetime } from "./profile-lifetime";

interface Props {
  destination: string;
  displayName: string;
  onAccepted: () => Promise<unknown>;
  onSendingChange: (sending: boolean) => void;
}

export function DirectMessageComposer(props: Props) {
  const lifetime = useProfileLifetime();
  const [resource, setResource] = useState<{ controller: DirectComposerController; textUtf8Bytes: number } | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    if (lifetime && !lifetime.active) return;
    const generation = lifetime?.capture();
    setResource(null);
    setError("");
    void openCoreComposer(props.destination).then(async ({ port, textUtf8Bytes }) => {
      if (!active || (lifetime && !lifetime.isCurrent(generation!))) return;
      const controller = new DirectComposerController(lifetime ? {
        query: (...args) => lifetime.isCurrent(generation!) ? port.query(...args) : Promise.reject(new ProfileRetiredError()),
        update: (...args) => lifetime.mutate(generation!, () => port.update(...args)),
        updateForRetirement: (...args) => lifetime.mutate(generation!, () => port.update(...args), true),
        enqueue: (...args) => lifetime.mutate(generation!, () => port.enqueue(...args)),
      } : port);
      setResource({ controller, textUtf8Bytes });
      await controller.load();
    }).catch((reason: unknown) => {
      const code = reason && typeof reason === "object" && "code" in reason ? reason.code : null;
      if (active && (!lifetime || lifetime.isCurrent(generation!))) setError(code === "unsupported_operation"
        ? "This runtime needs an update before saved drafts can be sent. Update Mesh Chat and reload the draft."
        : code === "forbidden" ? "This draft is not authorized for the contact. Check the connection approval before reloading."
          : code === "locked" ? "Unlock your profile before loading this draft."
            : "The saved draft is unavailable. Reload it before sending.");
    });
    return () => { active = false; };
  }, [props.destination, reload, lifetime]);

  if (!resource) return <div className="composer" aria-busy={!error}>
    <label className="sr-only" htmlFor="message-composer">Message {props.displayName}</label>
    <textarea id="message-composer" rows={1} value="" readOnly aria-label={`Message ${props.displayName}`} placeholder={error ? "Composer unavailable" : "Loading saved draft…"} />
    {error && <div><p role="alert">{error}</p><button type="button" onClick={() => setReload((value) => value + 1)}>Reload saved draft</button></div>}
    <button type="button" disabled aria-label="Send message"><Send size={19} /></button>
  </div>;

  return <LoadedComposer {...props} {...resource} />;
}

function LoadedComposer({ controller, textUtf8Bytes, ...props }: Props & {
  controller: DirectComposerController;
  textUtf8Bytes: number;
}) {
  const lifetime = useProfileLifetime();
  const view = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  const acceptedRevision = useRef<string | null>(null);
  const mounted = useRef(true);
  const [refreshError, setRefreshError] = useState("");
  const tooLarge = new TextEncoder().encode(view.text).byteLength > textUtf8Bytes;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!view.canSave || tooLarge) return;
    // Coalesce typing only. Core owns tokens, durable work and delivery policy.
    const timer = window.setTimeout(() => { void controller.save(); }, 250);
    return () => window.clearTimeout(timer);
  }, [controller, view.canSave, view.text, tooLarge]);

  useEffect(() => () => {
    if ((!lifetime || lifetime.active) && controller.getSnapshot().canSave) void controller.save();
  }, [controller, lifetime]);

  useEffect(() => {
    if (!lifetime || !lifetime.active) return;
    return lifetime.register(lifetime.capture(), async () => {
      await controller.freezeAndFlush();
      if (controller.getSnapshot().retry || controller.getSnapshot().recoveryText !== null) throw new Error("composer_outcome_pending");
    });
  }, [controller, lifetime]);

  useEffect(() => {
    props.onSendingChange(view.phase === "sending");
    return () => props.onSendingChange(false);
  }, [props.onSendingChange, view.phase]);

  useEffect(() => {
    if (view.saved?.status !== "accepted" || acceptedRevision.current === view.saved.revision) return;
    acceptedRevision.current = view.saved.revision;
    const revision = view.saved.revision;
    setRefreshError("");
    void props.onAccepted().catch(() => {
      if (mounted.current && acceptedRevision.current === revision) setRefreshError("Your message was saved. The conversation could not refresh yet.");
    });
  }, [props.onAccepted, view.saved]);

  const send = () => { if (!tooLarge) void controller.send(); };
  return <div>
    {view.saved?.status === "accepted" && <details className="composer-saved" role="status">
      <summary>Message saved on this device. View saved text</summary>
      <textarea readOnly aria-label="Saved message text" value={view.saved.text} />
    </details>}
    {view.saved?.status === "expired" && <p role="status">The previous saved message is no longer available for replay. Check the conversation before starting another send.</p>}
    {view.recoveryText !== null && <details open className="composer-recovery">
      <summary>Local text kept for review</summary>
      <textarea readOnly aria-label="Local text kept for review" value={view.recoveryText} />
      <button type="button" onClick={() => controller.restoreRecovery()}>Use my local text</button>
    </details>}
    <form className="composer" aria-busy={view.phase !== "ready"} onSubmit={(event) => { event.preventDefault(); send(); }}>
      {(view.error || refreshError || tooLarge) && <p className="composer__error" role="alert">{view.error || refreshError || `This draft exceeds the ${textUtf8Bytes}-byte text limit. Shorten it before saving or sending.`}</p>}
      <label className="sr-only" htmlFor="message-composer">Message {props.displayName}</label>
      <textarea id="message-composer" rows={1} value={view.text} readOnly={!view.loaded || view.phase === "loading"}
        enterKeyHint="send" onChange={(event) => { setRefreshError(""); controller.edit(event.target.value); }}
        placeholder={`Message ${props.displayName}`} maxLength={textUtf8Bytes}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }} />
      <button type="submit" disabled={!view.canSend || tooLarge} aria-label="Send message"><Send size={19} /></button>
      {view.retry && <button type="button" disabled={view.phase !== "ready"} onClick={() => { void controller.retry(); }}>{view.retry === "save" ? "Retry draft save" : "Retry previous send"}</button>}
      {view.error && <button type="button" disabled={view.phase !== "ready"} onClick={() => { void controller.load(); }}>Reload saved draft</button>}
    </form>
  </div>;
}
