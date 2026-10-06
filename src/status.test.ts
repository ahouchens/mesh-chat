import { describe, expect, it } from "vitest";
import { contactConnectionLabel, deliveryLabel } from "./status";
import type { Contact } from "./types";

describe("plain-language status mapping", () => {
  it("does not call native endpoint evidence delivered", () => {
    expect(deliveryLabel.received_by_endpoint).toBe("Received by their device");
    expect(deliveryLabel.stored_for_delivery).not.toContain("Delivered");
    expect(deliveryLabel.delivered).toBe("Delivered");
  });

  it("does not claim a request is awaiting acceptance before endpoint evidence", () => {
    const contact = {
      display_name: "Alex",
      trust: "awaiting_consent",
      request_state: "waiting_for_keys",
    } as Contact;
    expect(contactConnectionLabel(contact)).toBe(
      "Trying to reach Alex. Keep both apps open on the same local network.",
    );
  });

  it.each(["received_by_endpoint", "delivered"] as const)(
    "describes consent as pending after %s evidence",
    (request_state) => {
      const contact = {
        display_name: "Alex",
        trust: "awaiting_consent",
        request_state,
      } as Contact;
      expect(contactConnectionLabel(contact)).toBe(
        "Request reached Alex’s device. Waiting for acceptance.",
      );
    },
  );

  it("treats a missing request state as still trying to reach the peer", () => {
    const contact = {
      display_name: "Alex",
      trust: "awaiting_consent",
    } as Contact;
    expect(contactConnectionLabel(contact)).toContain("Trying to reach Alex");
  });
});
