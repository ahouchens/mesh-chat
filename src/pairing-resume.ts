const KEY = "meshchat.pairing.resume";
const TTL_MS = 10 * 60 * 1000;

export interface PairingResume {
  code: string;
  role: "offer" | "answer";
  savedAt: number;
}

export function savePairingResume(code: string, role: PairingResume["role"]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ code, role, savedAt: Date.now() }));
  } catch {
    // Resume is best effort; pairing still works in the current session.
  }
}

export function loadPairingResume(now = Date.now()): PairingResume | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PairingResume>;
    if (typeof value.code !== "string" || !value.code) return null;
    if (value.role !== "offer" && value.role !== "answer") return null;
    if (typeof value.savedAt !== "number" || now - value.savedAt > TTL_MS) {
      localStorage.removeItem(KEY);
      return null;
    }
    return { code: value.code, role: value.role, savedAt: value.savedAt };
  } catch {
    return null;
  }
}

export function clearPairingResume(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}
