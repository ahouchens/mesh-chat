import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Ellipsis } from "lucide-react";
import "./WorkspaceMessageMenu.css";

type MessageAction = {
  id: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  danger?: boolean;
};

export function WorkspaceMessageMenu({ authorName, actions }: { authorName: string; actions: MessageAction[] }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ left: number; top: number; maxHeight: number; maxWidth: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const initialFocus = useRef<"first" | "last">("first");
  const menuId = useId();
  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    setPosition(null);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const viewport = window.visualViewport;
      const leftEdge = (viewport?.offsetLeft ?? 0) + 8;
      const topEdge = (viewport?.offsetTop ?? 0) + 8;
      const maxWidth = Math.max(0, (viewport?.width ?? window.innerWidth) - 16);
      const maxHeight = Math.max(0, (viewport?.height ?? window.innerHeight) - 16);
      const triggerBounds = trigger.getBoundingClientRect();
      const menuBounds = menu.getBoundingClientRect();
      const width = Math.min(menuBounds.width || 240, maxWidth);
      const height = Math.min(menuBounds.height, maxHeight);
      const below = triggerBounds.bottom + 6;
      const top = below + height <= topEdge + maxHeight ? below : triggerBounds.top - height - 6;
      setPosition({
        left: Math.max(leftEdge, Math.min(triggerBounds.right - width, leftEdge + maxWidth - width)),
        top: Math.max(topEdge, Math.min(top, topEdge + maxHeight - height)),
        maxHeight,
        maxWidth,
      });
    };
    place();
    const items = menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    (initialFocus.current === "last" ? items?.[items.length - 1] : items?.[0])?.focus();
    window.addEventListener("resize", place);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    return () => {
      window.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
    };
  }, [open, actions.length]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) close();
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    const scroll = (event: Event) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) close();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    document.addEventListener("scroll", scroll, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape, true);
      document.removeEventListener("scroll", scroll, true);
    };
  }, [open, close]);

  const navigate = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Tab") { close(); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : event.key === "ArrowDown" ? (current + 1) % items.length
        : (current - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  return <>
    <button
      ref={triggerRef}
      type="button"
      className="workspace-message-menu-trigger"
      aria-label={`More actions for message from ${authorName}`}
      title="More message actions"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      onClick={() => { if (open) close(); else { initialFocus.current = "first"; setOpen(true); } }}
      onKeyDown={(event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        initialFocus.current = event.key === "ArrowUp" ? "last" : "first";
        setOpen(true);
      }}
    ><Ellipsis size={19} aria-hidden="true" /></button>
    {open && createPortal(<div
      ref={menuRef}
      id={menuId}
      className="workspace-message-menu"
      role="menu"
      aria-label={`Actions for message from ${authorName}`}
      style={position ?? { left: 8, top: 8 }}
      onKeyDown={navigate}
      onBlur={(event) => {
        if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== triggerRef.current) close(false);
      }}
    >{actions.map((action) => <button
      key={action.id}
      type="button"
      role="menuitem"
      tabIndex={-1}
      className={action.danger ? "workspace-message-menu__danger" : undefined}
      onClick={() => { close(); action.onSelect(); }}
    >{action.icon}<span>{action.label}</span></button>)}</div>, document.body)}
  </>;
}
