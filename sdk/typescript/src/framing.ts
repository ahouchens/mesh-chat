/** Strict single-line framing for the experimental Core API v1. */

import { ProtocolError } from "./errors.js";

export const API_VERSION = 1;
export const MAX_FRAME_BYTES = 4 * 1024 * 1024;
const REQUEST_ID = /^[A-Za-z0-9._:-]{1,80}$/;

export interface RequestEnvelope {
  api_version: 1;
  request_id: string;
  operation: string;
  params: Record<string, unknown>;
  idempotency_key?: string;
}

export type ResponseEnvelope =
  | { api_version: 1; request_id: string | null; ok: true; result: unknown }
  | {
      api_version: 1;
      request_id: string | null;
      ok: false;
      error: { code: string; retry_after_ms: number | null };
    };

export function encodeRequest(value: RequestEnvelope): string {
  if (!REQUEST_ID.test(value.request_id)) {
    throw new ProtocolError("request id is outside the declared grammar");
  }
  const line = `${JSON.stringify(value)}\n`;
  if (Buffer.byteLength(line, "utf8") > MAX_FRAME_BYTES) {
    throw new ProtocolError("request frame exceeds the negotiated ceiling");
  }
  return line;
}

export function decodeResponse(line: string): ResponseEnvelope {
  if (typeof line !== "string" || line.length === 0) {
    throw new ProtocolError("response frame is empty");
  }
  const body = line.endsWith("\r\n") ? line.slice(0, -2) : line.endsWith("\n") ? line.slice(0, -1) : null;
  if (body === null) {
    throw new ProtocolError("response frame is not line delimited");
  }
  if (Buffer.byteLength(body, "utf8") > MAX_FRAME_BYTES) {
    throw new ProtocolError("response frame exceeds the negotiated ceiling");
  }
  if (body.startsWith("\uFEFF")) {
    throw new ProtocolError("response frame starts with a byte-order mark");
  }
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    throw new ProtocolError("response frame is not JSON");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProtocolError("response frame is not an object");
  }
  const record = value as Record<string, unknown>;
  if (record.api_version !== API_VERSION) {
    throw new ProtocolError("response api version is unsupported");
  }
  const requestId = record.request_id;
  if (requestId !== null && !(typeof requestId === "string" && REQUEST_ID.test(requestId))) {
    throw new ProtocolError("response correlation is invalid");
  }
  if (record.ok === true) {
    if (!("result" in record)) {
      throw new ProtocolError("successful response has no result");
    }
    return { api_version: 1, request_id: requestId, ok: true, result: record.result };
  }
  if (record.ok === false) {
    const error = record.error;
    if (typeof error !== "object" || error === null) {
      throw new ProtocolError("failed response has no typed error");
    }
    const fields = error as Record<string, unknown>;
    if (typeof fields.code !== "string" || fields.code.length === 0) {
      throw new ProtocolError("failed response has no error code");
    }
    const retry = fields.retry_after_ms;
    if (retry !== null && !(typeof retry === "number" && Number.isFinite(retry) && retry >= 0)) {
      throw new ProtocolError("failed response has an invalid retry hint");
    }
    return {
      api_version: 1,
      request_id: requestId,
      ok: false,
      error: { code: fields.code, retry_after_ms: retry },
    };
  }
  throw new ProtocolError("response outcome is not a boolean");
}
