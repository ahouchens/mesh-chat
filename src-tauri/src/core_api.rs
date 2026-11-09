//! Minimal Core API line client for the trusted desktop shell.
//!
//! The shell owns the pipe name and client-image allowlist; this module only
//! speaks the versioned request/response envelope.

use serde_json::{json, Value};
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};

pub const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;

pub const API_VERSION: u64 = 1;

pub struct CoreApiClient {
    reader: BufReader<File>,
    writer: File,
    next: u64,
}

impl CoreApiClient {
    pub fn connect(name: &str) -> Result<Self, String> {
        let path = format!(r"\\.\pipe\{}", name.trim_start_matches(r"\\.\pipe\"));
        let writer = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .map_err(|_| "core_api_unavailable".to_string())?;
        let reader = BufReader::new(
            writer
                .try_clone()
                .map_err(|_| "core_api_unavailable".to_string())?,
        );
        Ok(Self {
            reader,
            writer,
            next: 0,
        })
    }

    pub fn request(&mut self, operation: &str, params: Value) -> Result<Value, String> {
        self.request_inner(operation, params, None)
    }

    pub fn request_with_key(
        &mut self,
        operation: &str,
        params: Value,
        idempotency_key: &str,
    ) -> Result<Value, String> {
        self.request_inner(operation, params, Some(idempotency_key))
    }

    fn request_inner(
        &mut self,
        operation: &str,
        params: Value,
        idempotency_key: Option<&str>,
    ) -> Result<Value, String> {
        self.next += 1;
        let request_id = format!("core:{}", self.next);
        let envelope = request_envelope(&request_id, operation, params, idempotency_key);
        exchange(&mut self.reader, &mut self.writer, &envelope, &request_id)
    }

    pub fn capabilities(&mut self) -> Result<Value, String> {
        self.request("runtime.capabilities", json!({}))
    }
}

fn request_envelope(request_id: &str, operation: &str, params: Value, key: Option<&str>) -> Value {
    let mut envelope = json!({
        "api_version": API_VERSION,
        "request_id": request_id,
        "operation": operation,
        "params": params,
    });
    if let Some(key) = key {
        envelope["idempotency_key"] = json!(key);
    }
    envelope
}

fn exchange(
    reader: &mut impl BufRead,
    writer: &mut impl Write,
    envelope: &Value,
    request_id: &str,
) -> Result<Value, String> {
    let mut frame = serde_json::to_vec(envelope).map_err(|_| "core_api_protocol".to_string())?;
    frame.push(b'\n');
    if frame.len() > MAX_FRAME_BYTES {
        return Err("invalid_request".into());
    }
    writer
        .write_all(&frame)
        .and_then(|_| writer.flush())
        .map_err(|_| "core_api_write_failed".to_string())?;
    let mut reply = Vec::new();
    reader
        .take((MAX_FRAME_BYTES + 1) as u64)
        .read_until(b'\n', &mut reply)
        .map_err(|_| "core_api_read_failed".to_string())?;
    if reply.len() > MAX_FRAME_BYTES || reply.last() != Some(&b'\n') {
        return Err("core_api_protocol".into());
    }
    let response: Value =
        serde_json::from_slice(&reply).map_err(|_| "core_api_protocol".to_string())?;
    validate(&response, request_id)
}

fn validate(response: &Value, request_id: &str) -> Result<Value, String> {
    if response.get("api_version").and_then(Value::as_u64) != Some(API_VERSION) {
        return Err("core_api_protocol".into());
    }
    let correlated = response.get("request_id").and_then(Value::as_str) == Some(request_id);
    let admission_failure = response.get("request_id").is_some_and(Value::is_null)
        && response.get("ok").and_then(Value::as_bool) == Some(false)
        && matches!(
            response.pointer("/error/code").and_then(Value::as_str),
            Some("forbidden" | "invalid_request" | "resource_exhausted" | "unavailable")
        );
    if !correlated && !admission_failure {
        return Err("core_api_protocol".into());
    }
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        return response
            .get("result")
            .cloned()
            .ok_or_else(|| "core_api_protocol".into());
    }
    if response.get("ok").and_then(Value::as_bool) != Some(false) {
        return Err("core_api_protocol".into());
    }
    let error = response
        .get("error")
        .filter(|error| error.get("code").and_then(Value::as_str).is_some())
        .ok_or_else(|| "core_api_protocol".to_string())?;
    // Preserve the contract error, including retry hints and unknown-outcome
    // fields. The shell must never turn a refusal into an unavailable fallback.
    Err(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn request(response: &[u8], key: Option<&str>) -> (Result<Value, String>, Vec<u8>) {
        let envelope = request_envelope("core:1", "message.enqueue", json!({"text":"hello"}), key);
        let mut writer = Vec::new();
        let result = exchange(&mut Cursor::new(response), &mut writer, &envelope, "core:1");
        (result, writer)
    }

    #[test]
    fn exchanges_correlated_results_and_preserves_mutation_keys() {
        let (result, written) = request(
            b"{\"api_version\":1,\"request_id\":\"core:1\",\"ok\":true,\"result\":{\"accepted\":true}}\n",
            Some("stable-caller-key"));
        assert_eq!(result.unwrap()["accepted"], true);
        let frame: Value = serde_json::from_slice(&written).unwrap();
        assert_eq!(frame["idempotency_key"], "stable-caller-key");
        assert_eq!(frame["operation"], "message.enqueue");
        assert_eq!(frame["params"]["text"], "hello");
    }

    #[test]
    fn preserves_typed_server_failures_and_retry_metadata() {
        for code in [
            "forbidden",
            "invalid_request",
            "conflict",
            "unavailable",
            "resource_exhausted",
        ] {
            let response = json!({"api_version":1,"request_id":"core:1","ok":false,
                "error":{"code":code,"retry_after_ms":125,"outcome":"unknown"}});
            let bytes = format!("{response}\n");
            let error: Value =
                serde_json::from_str(&request(bytes.as_bytes(), None).0.unwrap_err()).unwrap();
            assert_eq!(error["code"], code);
            assert_eq!(error["retry_after_ms"], 125);
            assert_eq!(error["outcome"], "unknown");
        }
    }

    #[test]
    fn preserves_host_admission_failures_without_accepting_uncorrelated_results() {
        let bytes = b"{\"api_version\":1,\"request_id\":null,\"ok\":false,\"error\":{\"code\":\"resource_exhausted\",\"retry_after_ms\":null}}\n";
        let error: Value = serde_json::from_str(&request(bytes, None).0.unwrap_err()).unwrap();
        assert_eq!(error["code"], "resource_exhausted");
    }

    #[test]
    fn rejects_uncorrelated_malformed_and_unbounded_responses() {
        for response in [
            "{\"api_version\":1,\"request_id\":\"other\",\"ok\":true,\"result\":{}}\n",
            "{\"api_version\":1,\"request_id\":\"core:1\",\"ok\":false}\n",
            "{\"api_version\":2,\"request_id\":\"core:1\",\"ok\":true,\"result\":{}}\n",
            "{\"api_version\":1,\"request_id\":\"core:1\",\"ok\":true,\"result\":{}}",
            "not-json\n",
        ] {
            assert_eq!(
                request(response.as_bytes(), None).0.unwrap_err(),
                "core_api_protocol"
            );
        }
        assert_eq!(
            request(&vec![b' '; MAX_FRAME_BYTES + 1], None)
                .0
                .unwrap_err(),
            "core_api_protocol"
        );
    }
}
