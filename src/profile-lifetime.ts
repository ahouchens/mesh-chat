import { createContext, useContext } from "react";

export class ProfileRetiredError extends Error {
  readonly code = "profile_changed";
  constructor() { super("The profile lifetime changed."); }
}

export const PROFILE_RETIREMENT_GRACE_MS = 1000;
export type RetirementDisposition = "drained" | "pending";

/** Orders admitted UI work before retirement; never owns keys or delivery policy. */
export class ProfileLifetime {
  private generation = 0;
  private phase: "active" | "closing" | "inactive" | "opening" = "active";
  private retiringGeneration: number | null = null;
  private retirement: Promise<RetirementDisposition> | null = null;
  private mutations = new Set<Promise<unknown>>();
  private participants = new Set<() => Promise<unknown>>();

  capture(): number {
    if (this.phase !== "active") throw new ProfileRetiredError();
    return this.generation;
  }

  isCurrent(generation: number): boolean {
    return this.phase === "active" && generation === this.generation;
  }

  get active(): boolean { return this.phase === "active"; }

  register(generation: number, retire: () => Promise<unknown>): () => void {
    if (!this.isCurrent(generation)) return () => undefined;
    this.participants.add(retire);
    return () => { this.participants.delete(retire); };
  }

  mutate<T>(generation: number, action: () => Promise<T>, retirementWork = false): Promise<T> {
    if (!this.isCurrent(generation) && !(retirementWork && this.phase === "closing" && generation === this.retiringGeneration)) {
      return Promise.reject(new ProfileRetiredError());
    }
    const mutation = Promise.resolve().then(action);
    const admitted = this.mutations;
    admitted.add(mutation);
    const settled = () => { admitted.delete(mutation); };
    void mutation.then(settled, settled);
    return mutation;
  }

  retire(): Promise<RetirementDisposition> {
    if (this.retirement) return this.retirement;
    this.retiringGeneration = this.generation;
    this.generation += 1;
    this.phase = "closing";
    // Participants freeze synchronously before React unmount cleanup can run.
    const work = [...this.participants].map((retire) => {
      try { return retire(); } catch (error) { return Promise.reject(error); }
    });
    const admitted = this.mutations;
    const drain = (async (): Promise<RetirementDisposition> => {
      const results = await Promise.allSettled(work);
      while (admitted.size) await Promise.allSettled([...admitted]);
      return results.some((result) => result.status === "rejected") ? "pending" : "drained";
    })();
    this.retirement = new Promise<RetirementDisposition>((resolve) => {
      // A stalled renderer RPC cannot prevent the native host retirement fence.
      const deadline = setTimeout(() => resolve("pending"), PROFILE_RETIREMENT_GRACE_MS);
      void drain.then((result) => { clearTimeout(deadline); resolve(result); });
    }).then((result) => {
      this.phase = "inactive";
      this.retiringGeneration = null;
      this.participants.clear();
      this.mutations = new Set();
      return result;
    });
    return this.retirement;
  }

  beginOpening(): number {
    if (this.phase !== "inactive") throw new ProfileRetiredError();
    this.generation += 1;
    this.phase = "opening";
    return this.generation;
  }

  finishOpening(generation: number): boolean {
    if (this.phase !== "opening" || generation !== this.generation) return false;
    this.phase = "active";
    this.retirement = null;
    return true;
  }

  failOpening(generation: number): void {
    if (this.phase === "opening" && generation === this.generation) this.phase = "inactive";
  }
}

export const ProfileLifetimeContext = createContext<ProfileLifetime | null>(null);
export const useProfileLifetime = () => useContext(ProfileLifetimeContext);
