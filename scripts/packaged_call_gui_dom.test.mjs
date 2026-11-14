// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { readView, targetRect } from "./packaged_call_gui_dom.mjs";

function place(rows) {
  for (const [index, row] of rows.entries()) {
    row.getBoundingClientRect = () => ({ left: index * 40, top: 0, width: 30, height: 20 });
  }
  document.elementFromPoint = (x) => rows[Math.floor(x / 40)] || null;
}

beforeEach(() => {
  document.title = "Mesh Chat";
  document.body.innerHTML = '<div id="root"><main>Ready</main></div>';
});

describe("rendered installed-GUI selectors", () => {
  it("selects only the CallDialog footer Close despite its header Close", () => {
    document.body.insertAdjacentHTML("beforeend", `<section role="dialog" aria-modal="true" class="dialog">
      <div class="dialog__header"><h2>Call Independent peer</h2><button aria-label="Close"></button></div>
      <div class="dialog-actions"><button>Close</button></div></section>`);
    const buttons = [...document.querySelectorAll("button")];
    place(buttons);
    expect(targetRect("button", "Close", "dialog")).toBeNull();
    expect(targetRect("call_close", "Close", "dialog")).toEqual({ x: 55, y: 10 });
    expect(targetRect("onboarding_close", "Close", "dialog")).toBeNull();
  });

  it("selects the onboarding header only and accepts an external label", () => {
    document.body.insertAdjacentHTML("beforeend", `<label for="entry"><span>Display name</span></label>
      <input id="entry"><section role="dialog" aria-modal="true" class="dialog">
      <div class="dialog__header"><h2>Connect with WebRTC</h2><button aria-label="Close"></button></div></section>`);
    const input = document.querySelector("input");
    const close = document.querySelector("button");
    place([input, close]);
    expect(targetRect("field", "Display name", "page")).toEqual({ x: 15, y: 10 });
    expect(targetRect("onboarding_close", "Close", "dialog")).toEqual({ x: 55, y: 10 });
  });

  it("filters hidden candidates before checking ambiguity", () => {
    document.body.insertAdjacentHTML("beforeend", `<button>Send message</button><button style="display:none">Send message</button>`);
    place([...document.querySelectorAll("button")]);
    expect(targetRect("button", "Send message", "page")).toEqual({ x: 15, y: 10 });
  });

  it("matches exact message content, excluding timestamps, substrings, and duplicate receipts", () => {
    document.body.insertAdjacentHTML("beforeend", `<section class="conversation" aria-label="Conversation with Independent peer">
      <article class="message message--inbound"><time>receipt-123</time><p class="message-content__text">unrelated</p></article>
      <article class="message message--outbound"><p class="message-content__text">receipt-123 extra</p><span class="delivery--delivered"></span></article>
      </section>`);
    expect(readView("receipt-123").matchedCount).toBe(0);
    document.querySelector(".message--inbound .message-content__text").textContent = "receipt-123";
    expect(readView("receipt-123")).toMatchObject({ matchedCount: 1, matchedInbound: true,
      matchedOutboundDelivered: false });
    document.querySelector(".message--outbound .message-content__text").textContent = "receipt-123";
    expect(readView("receipt-123")).toMatchObject({ matchedCount: 2, matchedInbound: true,
      matchedOutboundDelivered: true });
  });
});
