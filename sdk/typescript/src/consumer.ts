/**
 * Resynchronizing consumer for the private change stream.
 *
 * It owns a replay cursor and deduplicates redelivered events. It never polls
 * on a timer, never reconnects a peer and never acks a position it has not
 * durably applied: the caller decides when to confirm.
 */

import { MAX_BATCH, type CoreClient } from "./client.js";
import { CoreError, ProtocolError } from "./errors.js";
import type { Acknowledgment, EventPage, SnapshotMessage } from "./types.js";

export interface ConsumerOptions {
  limit?: number;
  dedupe?: number;
}

interface SnapshotPage {
  messages: SnapshotMessage[];
  next_cursor: string | null;
  events_cursor: string | null;
}

export interface Resynchronized {
  messages: SnapshotMessage[];
  eventsCursor: string;
}

export class CoreConsumer {
  readonly #client: CoreClient;
  readonly #profile: string;
  readonly #limit: number;
  readonly #dedupe: number;
  #cursor: string | null = null;
  readonly #seen = new Set<string>();
  readonly #order: string[] = [];

  constructor(client: CoreClient, profile: string, options: ConsumerOptions = {}) {
    const limit = options.limit ?? MAX_BATCH;
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_BATCH) {
      throw new ProtocolError("consumer page limit is outside the declared bounds");
    }
    this.#client = client;
    this.#profile = profile;
    this.#limit = limit;
    this.#dedupe = options.dedupe ?? 2048;
  }

  /** Current replay position, or null when a fresh snapshot is required. */
  get cursor(): string | null {
    return this.#cursor;
  }

  /**
   * Read every snapshot page, then adopt its replay watermark. Changes committed
   * after the final page appear in the following poll, which closes the
   * query/subscribe race.
   */
  async resynchronize(): Promise<Resynchronized> {
    const messages: SnapshotMessage[] = [];
    let cursor: string | null = null;
    for (;;) {
      const page: SnapshotPage = await this.#client.request<SnapshotPage>("message.list", {
        profile: this.#profile,
        cursor,
        limit: this.#limit,
      });
      messages.push(...page.messages);
      if (page.next_cursor !== null) {
        cursor = page.next_cursor;
        continue;
      }
      if (page.events_cursor === null) {
        throw new ProtocolError("snapshot ended without a replay watermark");
      }
      this.#cursor = page.events_cursor;
      return { messages, eventsCursor: page.events_cursor };
    }
  }

  /**
   * Fetch one replay page. Duplicate event ids are returned at most once per
   * consumer, and `resync_required` clears the position instead of skipping.
   */
  async poll(): Promise<EventPage> {
    try {
      const page = await this.#client.pollEvents(this.#profile, this.#cursor, this.#limit);
      this.#cursor = page.next_cursor;
      return { ...page, events: page.events.filter((event) => this.#remember(event.id)) };
    } catch (error) {
      if (error instanceof CoreError && error.code === "resync_required") {
        this.#cursor = null;
      }
      throw error;
    }
  }

  /** Confirm the current position only after the caller has applied it. */
  async confirm(idempotencyKey: string): Promise<Acknowledgment> {
    if (this.#cursor === null) {
      throw new ProtocolError("consumer has no replay position to confirm");
    }
    return this.#client.acknowledge(this.#profile, this.#cursor, idempotencyKey);
  }

  #remember(identifier: string): boolean {
    if (this.#seen.has(identifier)) {
      return false;
    }
    this.#seen.add(identifier);
    this.#order.push(identifier);
    if (this.#order.length > this.#dedupe) {
      const evicted = this.#order.shift();
      if (evicted !== undefined) {
        this.#seen.delete(evicted);
      }
    }
    return true;
  }
}
