/** Pure SDP helpers shared by browser transport adapters. */
export function withEndOfCandidates(sdp: string): string {
  if (/(^|\r?\n)a=end-of-candidates(\r?\n|$)/.test(sdp)) return sdp;
  return `${sdp.replace(/\s*$/, "")}\r\na=end-of-candidates\r\n`;
}

export function fingerprint(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) {
      return line.slice("a=fingerprint:".length).trim();
    }
  }
  throw new Error("The offer has no DTLS fingerprint.");
}
