import { afterEach, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import vectors from "../contracts/connection/native-carrier-sdp-v1.vectors.json";
import { descriptionHash } from "./native-carrier-evidence";

afterEach(() => vi.unstubAllGlobals());

it.each(vectors)("matches the protected-service SDP binding vector: $name", async ({ sdp, sha256 }) => {
  vi.stubGlobal("crypto", webcrypto);
  expect(await descriptionHash(sdp)).toBe(sha256);
});

it("bounds description hashing and represents an absent description explicitly", async () => {
  vi.stubGlobal("crypto", webcrypto);
  expect(await descriptionHash(undefined)).toBeNull();
  await expect(descriptionHash("x".repeat(65537))).rejects.toThrow("invalid_transport_description");
});
