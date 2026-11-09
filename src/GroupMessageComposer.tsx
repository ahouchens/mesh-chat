import { useEffect, useRef, useState, type ReactNode } from "react";
import { openCoreGroupComposer } from "./core-group-composer";
import { ComposerController } from "./direct-composer";
import { SavedMessageComposer, type SavedComposerProps } from "./DirectMessageComposer";
import { ProfileRetiredError, useProfileLifetime } from "./profile-lifetime";

export function GroupMessageComposer({ group, legacyComposer, ...props }: SavedComposerProps & { group: string; legacyComposer: ReactNode }) {
  const lifetime = useProfileLifetime();
  const [resource, setResource] = useState<{ controller: ComposerController; textUtf8Bytes: number } | null>(null);
  const [legacy, setLegacy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const allowLegacy = useRef(true);
  useEffect(() => {
    let active = true;
    if (lifetime && !lifetime.active) return;
    const generation = lifetime?.capture();
    setResource(null); setLegacy(false); setError("");
    void openCoreGroupComposer(group).then(async (opened) => {
      if (!active || (lifetime && !lifetime.isCurrent(generation!))) return;
      if (!opened) {
        if (!allowLegacy.current) throw new Error("group_composer_unavailable");
        setLegacy(true); return;
      }
      allowLegacy.current = false;
      const { port, textUtf8Bytes } = opened;
      const controller = new ComposerController(lifetime ? {
        query: (...args) => lifetime.isCurrent(generation!) ? port.query(...args) : Promise.reject(new ProfileRetiredError()),
        update: (...args) => lifetime.mutate(generation!, () => port.update(...args)),
        updateForRetirement: (...args) => lifetime.mutate(generation!, () => port.update(...args), true),
        enqueue: (...args) => lifetime.mutate(generation!, () => port.enqueue(...args)),
      } : port);
      setResource({ controller, textUtf8Bytes }); await controller.load();
    }).catch(() => {
      allowLegacy.current = false;
      if (active && (!lifetime || lifetime.isCurrent(generation!))) setError("The saved group draft is unavailable. Reload it before sending.");
    });
    return () => { active = false; };
  }, [group, lifetime, reload]);
  if (legacy) return legacyComposer;
  if (resource) return <SavedMessageComposer {...props} {...resource} kind="group" />;
  return <div className="composer" aria-busy={!error}>
    {error ? <div><p role="alert">{error}</p><button type="button" onClick={() => setReload((value) => value + 1)}>Reload saved group draft</button></div>
      : <p role="status">Loading saved group draft…</p>}
  </div>;
}
