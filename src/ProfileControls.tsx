import { LockKeyhole } from "lucide-react";
import { Button } from "./Button";
import type { ProfileAction, ProfileCatalog } from "./core-profiles";

export function ProfileSelector({ catalog, disabled, onSelect }: {
  catalog: ProfileCatalog; disabled: boolean; onSelect: (profile: string) => void;
}) {
  return <section aria-label="Profiles" className="profile-catalog"><label>Selected profile
    <select aria-label="Selected profile" value={catalog.selected_profile ?? ""} disabled={disabled} onChange={(event) => onSelect(event.target.value)}>
      {catalog.profiles.map((row) => <option key={row.profile} value={row.profile}>{row.display_name} · {row.state}</option>)}
    </select>
  </label></section>;
}

export function ProfileLockScreen({ catalog, busy, pending, reviewRequired, retirementPending, error, onAction, onReview, onOpen }: {
  catalog: ProfileCatalog; busy: boolean; pending: ProfileAction | null; reviewRequired: boolean;
  retirementPending: boolean; error: string;
  onAction: (action?: ProfileAction["action"], profile?: string) => Promise<void>;
  onReview: () => Promise<void>; onOpen: () => Promise<void>;
}) {
  const selected = catalog.profiles.find((row) => row.selected);
  return <main className="fatal-screen"><LockKeyhole size={36} />
    <h1>{busy ? "Updating your profile…" : "Mesh Chat is locked"}</h1>
    <ProfileSelector catalog={catalog} disabled={busy || Boolean(pending) || reviewRequired || selected?.state === "retiring"} onSelect={(profile) => void onAction("select", profile)} />
    <p>Profile content is hidden. Unlock uses your device authentication.</p>
    {retirementPending && <p role="status">Some requests are still awaiting their saved outcomes.</p>}
    {selected?.state === "retiring" && <p role="status">Profile retirement is pending. Refreshing the catalog does not complete the previous action.</p>}
    {error && <p role="alert">{error}</p>}
    {pending && <p role="status">Previous {pending.action} action is awaiting confirmation.</p>}
    {pending && !reviewRequired && <Button disabled={busy} onClick={() => void onAction()}>Retry previous {pending.action}</Button>}
    {!pending && !reviewRequired && selected?.state === "locked" && <Button disabled={busy} onClick={() => void onAction("unlock", selected.profile)}>Unlock selected profile</Button>}
    {!pending && !reviewRequired && selected?.state === "unlocked" && <Button disabled={busy} onClick={() => void onOpen()}>Open selected profile</Button>}
    <Button variant="secondary" disabled={busy} onClick={() => void onReview()}>Review current profiles</Button>
  </main>;
}
