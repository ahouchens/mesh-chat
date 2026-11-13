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
  checkValues(value);
  if (!REQUEST_ID.test(value.request_id)) {
    throw new ProtocolError("request id is outside the declared grammar");
  }
  const line = `${JSON.stringify(value)}\n`;
  checkStructure(line);
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
  if (Buffer.byteLength(line, "utf8") > MAX_FRAME_BYTES) {
    throw new ProtocolError("response frame exceeds the negotiated ceiling");
  }
  if (body.startsWith("\uFEFF")) {
    throw new ProtocolError("response frame starts with a byte-order mark");
  }
  let value: unknown;
  try {
    checkStructure(body, false);
    value = JSON.parse(body);
    checkValues(value, false);
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
    if (typeof fields.code !== "string" || fields.code.length === 0 || fields.code.length > 80) {
      throw new ProtocolError("failed response has no error code");
    }
    const retry = fields.retry_after_ms;
    if (retry !== null && !(typeof retry === "number" && Number.isSafeInteger(retry) && retry >= 0 && retry <= 3600000)) {
      throw new ProtocolError("failed response has an invalid retry hint");
    }
    return {
      api_version: 1,
      request_id: requestId,
      ok: false,
      error: { ...fields, code: fields.code, retry_after_ms: retry },
    };
  }
  throw new ProtocolError("response outcome is not a boolean");
}

function checkValues(value: unknown, request = true): void {
  const pending: { value: unknown; depth: number }[] = [{ value, depth: 0 }];
  while (pending.length) {
    const { value, depth } = pending.pop()!;
    if (request && depth > 16) throw new ProtocolError("JSON depth exceeds limit");
    if (typeof value === "number" && (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)))) {
      throw new ProtocolError("JSON number is outside portable range");
    }
    if (typeof value === "string" && /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) {
      throw new ProtocolError("JSON string contains an unpaired surrogate");
    }
    if (Array.isArray(value)) for (const child of value) pending.push({ value: child, depth: depth + 1 });
    else if (value !== null && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) {
        pending.push({ value: key, depth: 0 }, { value: child, depth: depth + 1 });
      }
    }
  }
}

function checkStructure(text: string, request = true): void {
  const stack: ({ keys: Set<string>; expectingKey: boolean } | null)[] = [];
  let tokens = 0;
  for (let index = 0; index < text.length; index++) {
    const character = text[index]!;
    if (character === '"') {
      const start = index;
      for (index++; index < text.length; index++) {
        if (text[index] === "\\") index++;
        else if (text[index] === '"') break;
      }
      const top = stack.at(-1);
      if (top?.expectingKey) {
        const key: string = JSON.parse(text.slice(start, index + 1));
        if (top.keys.has(key)) throw new ProtocolError("duplicate JSON member");
        top.keys.add(key); top.expectingKey = false;
      }
    } else if ("{}[]:,".includes(character)) {
      if (++tokens > 1024 && request) throw new ProtocolError("JSON structural budget exceeded");
      if (character === "{") stack.push({ keys: new Set(), expectingKey: true });
      else if (character === "[") stack.push(null);
      else if (character === "}" || character === "]") stack.pop();
      else if (character === "," && stack.at(-1)) stack.at(-1)!.expectingKey = true;
      if (request && stack.length > 16) throw new ProtocolError("JSON depth exceeds limit");
    }
  }
}
