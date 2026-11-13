/** Private mechanism observations. Hashes are bindings, never caller authority. */
export async function descriptionHash(sdp: string | undefined) {
  if (sdp === undefined) return null;
  if (!sdp || new TextEncoder().encode(sdp).length > 65536) throw new Error("invalid_transport_description");
  // Match Python str.splitlines(), retaining every non-empty SDP line except
  // the optional gathering terminator used by the existing signed binding.
  const normalized = sdp.split(/\r\n|[\n\r\v\f\u001c-\u001e\u0085\u2028\u2029]/)
    .filter(line => line && line !== "a=end-of-candidates").join("\n");
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalized));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}

export function adapterEpoch() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
}
