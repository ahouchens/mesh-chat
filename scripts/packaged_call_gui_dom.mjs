// These observations select rendered controls only; input is dispatched by CDP.
export function targetRect(kind, label, scope) {
  const norm = (value) => (value || "").replace(/\s+/g, " ").trim();
  const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
  const root = scope === "dialog" ? dialog : document;
  if (!root) return null;
  let rows;
  if (kind === "button") rows = [...root.querySelectorAll("button")]
    .filter((row) => norm(row.getAttribute("aria-label")) === label || norm(row.textContent) === label);
  else if (kind === "call_close") rows = norm(dialog?.querySelector("h2")?.textContent) === "Call Independent peer"
    ? [...dialog.querySelectorAll(".dialog-actions button")].filter((row) => norm(row.textContent) === "Close") : [];
  else if (kind === "onboarding_close") rows = norm(dialog?.querySelector("h2")?.textContent) === "Connect with WebRTC"
    ? [...dialog.querySelectorAll('.dialog__header button[aria-label="Close"]')] : [];
  else if (kind === "peer") rows = [...root.querySelectorAll("button.contact-row")]
    .filter((row) => norm(row.querySelector(".contact-row__content strong")?.textContent) === label);
  else if (kind === "field") rows = [...root.querySelectorAll("label")]
    .filter((row) => norm(row.querySelector("span")?.textContent || row.textContent) === label)
    .map((row) => row.querySelector("input, textarea") ||
      (row.htmlFor ? document.getElementById(row.htmlFor) : null))
    .filter(Boolean);
  else return null;
  const eligible = rows.map((row) => {
    if (row.disabled || row.readOnly) return null;
    const box = row.getBoundingClientRect();
    const style = getComputedStyle(row);
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const hit = document.elementFromPoint(x, y);
    if (box.width < 2 || box.height < 2 || style.display === "none" || style.visibility !== "visible"
        || !hit || !(row === hit || row.contains(hit))) return null;
    return { x, y };
  }).filter(Boolean);
  return eligible.length === 1 ? eligible[0] : null;
}

export function readView(expectedText) {
  const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
  const status = [...(dialog?.querySelectorAll('[role="status"]') || [])]
    .map((row) => row.textContent?.replace(/\s+/g, " ").trim()).filter(Boolean)[0] || "";
  const conversation = document.querySelector('section.conversation[aria-label]');
  const messages = [...(conversation?.querySelectorAll("article.message") || [])];
  const matched = typeof expectedText === "string" && expectedText.length > 0
    ? messages.filter((row) => row.querySelector(".message-content__text")?.textContent === expectedText) : [];
  return { appMounted: Boolean(document.querySelector("#root > *")) && document.title === "Mesh Chat",
    dialogTitle: dialog?.querySelector("h2")?.textContent?.trim().slice(0, 100) || null,
    status: status.slice(0, 160), conversationOpen: Boolean(conversation),
    callEnabled: Boolean(conversation?.querySelector('button[aria-label="Call Independent peer"]:not([disabled])')),
    peerVisible: [...document.querySelectorAll("button.contact-row .contact-row__content strong")]
      .some((row) => row.textContent?.trim() === "Independent peer"),
    relayOption: [...(dialog?.querySelectorAll("button") || [])].some((row) =>
      row.textContent?.replace(/\s+/g, " ").trim() === "Use the relay"),
    relayPanelVisible: [...(dialog?.querySelectorAll("h3") || [])].some((row) =>
      row.textContent?.trim() === "Internet relay is available"),
    contactPreview: [...(dialog?.querySelectorAll("button") || [])].some((row) =>
      row.textContent?.replace(/\s+/g, " ").trim() === "Accept contact"),
    matchedCount: Math.min(matched.length, 2),
    matchedInbound: matched.some((row) => row.classList.contains("message--inbound")),
    matchedOutboundDelivered: matched.some((row) => row.classList.contains("message--outbound") &&
      Boolean(row.querySelector(".delivery--delivered"))) };
}
