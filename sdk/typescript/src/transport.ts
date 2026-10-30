/** One framed, line-oriented connection owned by a trusted host. */
export interface LineTransport {
  /** Resolve the next complete line (including its delimiter) or null at EOF. */
  readLine(): Promise<string | null>;
  /** Write one complete frame; short writes must be handled by the transport. */
  writeLine(line: string): Promise<void>;
  close(): void;
}
