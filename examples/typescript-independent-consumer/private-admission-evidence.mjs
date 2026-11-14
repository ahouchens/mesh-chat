// Exact post-removal evidence for one public helper session.
import { randomUUID } from "node:crypto";
import { HelperCoreError } from "./public-process-helper.mjs";

export async function requireRevokedHelper(helper, profile, settings, deadline) {
  try {
    await helper.request("settings.update", {profile, settings}, deadline, randomUUID());
  } catch (error) {
    if (!(error instanceof HelperCoreError) || error.code !== "unauthenticated") {
      throw new Error("helper_revocation_not_proven");
    }
    await helper.closeInput(deadline); // Exit 0, no stderr, no malformed output.
    return;
  }
  throw new Error("removed_helper_mutated");
}
