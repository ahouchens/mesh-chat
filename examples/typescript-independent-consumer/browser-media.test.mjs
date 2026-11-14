import assert from "node:assert";
import { boundedTargets } from "./browser-media.mjs";

function body(bytes) {
  let seen = false;
  let cancelled = false;
  return { response: { body: { getReader: () => ({
    async read() {
      if (seen) return { done: true };
      seen = true;
      return { done: false, value: bytes };
    },
    async cancel() { cancelled = true; },
  }) } }, wasCancelled: () => cancelled };
}

const valid = body(new TextEncoder().encode('[{"type":"page"}]'));
assert.deepStrictEqual(await boundedTargets(valid.response), [{ type: "page" }]);
const oversized = body(new Uint8Array(65537));
await assert.rejects(boundedTargets(oversized.response), /browser_target_body_limit/);
assert.equal(oversized.wasCancelled(), true);
const malformed = body(new TextEncoder().encode("{"));
await assert.rejects(boundedTargets(malformed.response), SyntaxError);
