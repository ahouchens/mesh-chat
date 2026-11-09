import { afterEach, expect, it, vi } from "vitest";
import { ProfileLifetime, ProfileRetiredError, PROFILE_RETIREMENT_GRACE_MS } from "./profile-lifetime";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((finish) => { resolve = finish; });
  return { promise, resolve };
}

afterEach(() => vi.useRealTimers());

it("invalidates reads immediately, freezes participants and drains admitted work before retirement", async () => {
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const admitted = deferred();
  const flush = deferred();
  const freeze = vi.fn(() => lifetime.mutate(generation, () => flush.promise, true));
  lifetime.register(generation, freeze);
  const mutation = lifetime.mutate(generation, () => admitted.promise);
  const retirement = lifetime.retire();
  expect(freeze).toHaveBeenCalledOnce();
  expect(lifetime.isCurrent(generation)).toBe(false);
  expect(() => lifetime.capture()).toThrow(ProfileRetiredError);
  const late = vi.fn(async () => undefined);
  await expect(lifetime.mutate(generation, late)).rejects.toThrow(ProfileRetiredError);
  expect(late).not.toHaveBeenCalled();
  let finished = false;
  void retirement.then(() => { finished = true; });
  flush.resolve();
  await Promise.resolve();
  expect(finished).toBe(false);
  admitted.resolve();
  await mutation;
  await expect(retirement).resolves.toBe("drained");
  await expect(lifetime.mutate(generation, late, true)).rejects.toThrow(ProfileRetiredError);
});

it("bounds a never resolving flush and prevents its late continuation from mutating a reopened profile", async () => {
  vi.useFakeTimers();
  const lifetime = new ProfileLifetime();
  const old = lifetime.capture();
  const stalled = deferred();
  const late = vi.fn(async () => undefined);
  let blocked = false;
  lifetime.register(old, async () => {
    await lifetime.mutate(old, () => stalled.promise, true);
    await lifetime.mutate(old, late, true).catch(() => { blocked = true; });
  });
  const retirement = lifetime.retire();
  expect(lifetime.retire()).toBe(retirement);
  await vi.advanceTimersByTimeAsync(PROFILE_RETIREMENT_GRACE_MS);
  await expect(retirement).resolves.toBe("pending");
  const opening = lifetime.beginOpening();
  expect(lifetime.finishOpening(opening)).toBe(true);
  const current = lifetime.capture();
  expect(lifetime.isCurrent(old)).toBe(false);
  stalled.resolve();
  await vi.runAllTimersAsync();
  expect(blocked).toBe(true);
  expect(late).not.toHaveBeenCalled();
  expect(lifetime.isCurrent(current)).toBe(true);
  await expect(lifetime.retire()).resolves.toBe("drained");
});

it("keeps an unsuccessful opening inactive until a new opening completes", async () => {
  const lifetime = new ProfileLifetime();
  await lifetime.retire();
  const failed = lifetime.beginOpening();
  lifetime.failOpening(failed);
  const opened = lifetime.beginOpening();
  expect(lifetime.finishOpening(failed)).toBe(false);
  expect(lifetime.finishOpening(opened)).toBe(true);
  expect(lifetime.isCurrent(opened)).toBe(true);
});
