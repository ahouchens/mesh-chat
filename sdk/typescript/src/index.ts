export { CoreClient, DEFAULT_TIMEOUT_MS, MAX_BATCH, MAX_DIAGNOSTICS } from "./client.js";
export type { CoreClientOptions, RequestOptions } from "./client.js";
export { API_VERSION, MAX_FRAME_BYTES, decodeResponse, encodeRequest } from "./framing.js";
export type { RequestEnvelope, ResponseEnvelope } from "./framing.js";
export { AbortError, CoreError, ProtocolError, TimeoutError, TransportClosedError } from "./errors.js";
export { CoreConsumer } from "./consumer.js";
export type { ConsumerOptions, Resynchronized } from "./consumer.js";
export type { LineTransport } from "./transport.js";
export type {
  Acceptance,
  Acknowledgment,
  Capabilities,
  ConnectionView,
  DiagnosticsView,
  EventPage,
  MessageEvent,
  ProfileView,
  ReceivedMessage,
  ReceivedPage,
  SnapshotMessage,
} from "./types.js";
