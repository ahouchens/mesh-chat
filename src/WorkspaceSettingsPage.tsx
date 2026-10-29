import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ChevronRight, Settings, Users, Smartphone, History, Network, ShieldCheck, Radio } from "lucide-react";
import "./WorkspaceSettingsPage.css";

const sections = [
  { id: "general", title: "General", description: "Workspace details, permissions and notifications", icon: Settings },
  { id: "people", title: "People", description: "Members, roles and administrative requests", icon: Users },
  { id: "devices", title: "Devices", description: "Linked devices and read synchronization", icon: Smartphone },
  { id: "history", title: "History & retention", description: "Catch up on messages and manage local history", icon: History },
  { id: "connections", title: "Connections", description: "Recovery, reconnection and offline delivery", icon: Network },
  { id: "access", title: "Access points", description: "Review and approve workspace access points", icon: Radio },
  { id: "authority", title: "Ownership & recovery", description: "Transfer authority or recover workspace administration", icon: ShieldCheck },
] as const;
export type WorkspaceSettingsSection = typeof sections[number]["id"];

/** Embedded forms keep their existing permission checks and action handlers. */
export function WorkspaceSettingsPanel({ children }: { children: ReactNode }) {
  return <div className="workspace-settings-panel">{children}</div>;
}

export function WorkspaceSettingsPage({ name, role, section, panels, busy, pendingRequests = 0, pendingDevices = 0, pendingAuthority = 0, onSelect, onClose, onBackHandlerChange }: {
  name: string; role: string; section: WorkspaceSettingsSection;
  panels: Record<WorkspaceSettingsSection, ReactNode>; busy: boolean; pendingRequests?: number; pendingDevices?: number; pendingAuthority?: number;
  onSelect: (section: WorkspaceSettingsSection) => void; onClose: () => void;
  onBackHandlerChange?: (handler: (() => void) | null) => void;
}) {
  const [index, setIndex] = useState(section === "general");
  const [visited, setVisited] = useState<Set<WorkspaceSettingsSection>>(() => new Set([section]));
  const titleRef = useRef<HTMLHeadingElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);
  const active = sections.find(item => item.id === section)!;
  const pending: Partial<Record<WorkspaceSettingsSection, number>> = { people: pendingRequests, devices: pendingDevices, authority: pendingAuthority };
  const back = useCallback(() => {
    if (busy) return;
    if (window.innerWidth <= 760 && !index) setIndex(true);
    else onClose();
  }, [busy, index, onClose]);
  useEffect(() => { onBackHandlerChange?.(back); return () => onBackHandlerChange?.(null); }, [back, onBackHandlerChange]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && !document.querySelector('[role="dialog"]')) { event.preventDefault(); back(); }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [back]);
  useEffect(() => () => { if (opener.current?.isConnected) opener.current.focus(); }, []);
  useEffect(() => { setVisited(current => new Set([...current, section])); }, [section]);
  useLayoutEffect(() => { titleRef.current?.focus(); if (contentRef.current) contentRef.current.scrollTop = 0; }, [section, index]);
  const select = (next: WorkspaceSettingsSection) => { setIndex(false); onSelect(next); };
  return <section className={`workspace-settings-page ${index ? "workspace-settings-page--index" : ""}`} aria-label={`Workspace settings for ${name}`}>
    <header className="workspace-settings-page__header">
      <button type="button" className="settings-page__back" disabled={busy} onClick={back} aria-label="Back from workspace settings"><ArrowLeft size={20} /> Back</button>
      <div><h1 ref={titleRef} tabIndex={-1}>Workspace settings</h1><p>{name} <span>· {role === "admin" ? "Administrator" : role === "owner" ? "Owner" : "Member"}</span></p></div>
      {busy && <span role="status">Saving…</span>}
    </header>
    <div className="workspace-settings-page__body">
      <nav className="workspace-settings-page__nav" aria-label="Workspace settings sections">
        {sections.map(({ id, title, description, icon: Icon }) => <button key={id} type="button" aria-current={section === id ? "page" : undefined} disabled={busy} onClick={() => select(id)}>
          <Icon size={20} /><span><strong>{title}{(pending[id] ?? 0) > 0 && <small className="workspace-settings-page__badge">{pending[id]} pending</small>}</strong><small>{description}</small></span><ChevronRight size={16} />
        </button>)}
      </nav>
      <div className="workspace-settings-page__content" ref={contentRef}>
        <button className="workspace-settings-page__all" type="button" disabled={busy} onClick={() => setIndex(true)}><ArrowLeft size={16} /> All workspace settings</button>
        <div className="workspace-settings-page__heading"><h2>{active.title}</h2><p>{active.description}</p></div>
        {sections.filter(item => item.id === section || visited.has(item.id)).map(item => <section key={item.id} hidden={item.id !== section} aria-label={item.title}>{panels[item.id]}</section>)}
      </div>
    </div>
  </section>;
}
