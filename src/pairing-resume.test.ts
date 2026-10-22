import { beforeEach, describe, expect, it } from "vitest";
import { clearPairingResume, loadPairingResume, savePairingResume } from "./pairing-resume";

describe("pairing resume", () => {
  beforeEach(() => {
    localStorage.clear();
    clearPairingResume();
  });

  it("round-trips a fresh pairing code", () => {
    savePairingResume("a".repeat(24), "offer");
    const value = loadPairingResume();
    expect(value?.code).toBe("a".repeat(24));
    expect(value?.role).toBe("offer");
  });

  it("drops expired or malformed entries", () => {
    localStorage.setItem("meshchat.pairing.resume", JSON.stringify({ code: "old", role: "offer", savedAt: 0 }));
    expect(loadPairingResume(11 * 60 * 1000)).toBeNull();
    expect(localStorage.getItem("meshchat.pairing.resume")).toBeNull();

    localStorage.setItem("meshchat.pairing.resume", JSON.stringify({ code: "", role: "offer", savedAt: Date.now() }));
    expect(loadPairingResume()).toBeNull();
  });
});
