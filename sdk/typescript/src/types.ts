/** Selected public shapes; every field is explicitly chosen by the facade. */

export interface Capabilities {
  api_major: number;
  api_minor: number;
  stability: string;
  operations: string[];
  profiles: string[];
  limits: Record<string, number>;
}

export interface ProfileView {
  profile: string;
  display_name: string;
  destination: string;
  connections: string[];
  peers?: string[];
}

export interface ConnectionView {
  profile: string;
  connection: string;
  observation: Record<string, unknown>;
}

export interface SnapshotMessage {
  profile: string;
  message: string;
  recipient: string;
  kind: "text";
  text: string;
  state: string;
  created_at: number;
}

export interface ReceivedMessage {
  profile: string;
  message: string;
  peer: string;
  kind: "text";
  text: string;
  state: string;
  created_at: number;
}

export interface ReceivedPage {
  profile: string;
  messages: ReceivedMessage[];
  next_cursor: string | null;
  more: boolean;
}

export interface MessageEvent {
  id: string;
  message: string;
  type: "message.changed" | "message.removed";
  state: string | null;
  timestamp: number;
  direction: "inbound" | "outbound";
}

export interface EventPage {
  profile: string;
  events: MessageEvent[];
  next_cursor: string;
  more: boolean;
}

export interface Acceptance {
  profile: string;
  message: string;
  accepted: true;
  accepted_at: number;
  idempotency_expires_at: number;
}

export interface Acknowledgment {
  profile: string;
  checkpoint: string;
  acknowledged: true;
  acknowledged_at: number;
  expires_at: number;
}

export interface DiagnosticsView {
  profile: string;
  captured_at?: number;
  available?: boolean;
  runtime_failure?: string | null;
  connections?: Record<string, unknown>[];
  total_connections?: number;
  truncated?: boolean;
}
