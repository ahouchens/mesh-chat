const KEY = "meshchat.pairing.resume";
const TTL_MS = 10 * 60 * 1000;

export interface PairingResume {
  code: string;
  role: "offer" | "answer";
  savedAt: number;
}

// Encrypted invitations contain decryption keys. Keep resume state in memory,
// never in unsealed browser storage; a process restart needs a fresh invitation.
let current: PairingResume | null = null;
function removeLegacy(): void {
  try { localStorage.removeItem(KEY); } catch { /* Storage unavailable. */ }
}

export function savePairingResume(code: string, role: PairingResume["role"]): void {
  removeLegacy();
  current = { code, role, savedAt: Date.now() };
}

export function loadPairingResume(now = Date.now()): PairingResume | null {
  removeLegacy();
  if (current && (now - current.savedAt > TTL_MS || now < current.savedAt)) current = null;
  return current ? { ...current } : null;
}

export function clearPairingResume(): void {
  current = null;
  removeLegacy();
}