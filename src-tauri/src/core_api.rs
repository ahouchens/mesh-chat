//! Minimal Core API line client for the trusted desktop shell.
//!
//! The shell owns the pipe name and client-image allowlist; this module only
//! speaks the versioned request/response envelope.

use serde_json::{json, Value};
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};

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
        let mut envelope = json!({
            "api_version": API_VERSION,
            "request_id": request_id,
            "operation": operation,
            "params": params,
        });
        if let Some(key) = idempotency_key {
            envelope["idempotency_key"] = json!(key);
        }
        self.writer
            .write_all(format!("{envelope}\n").as_bytes())
            .and_then(|_| self.writer.flush())
            .map_err(|_| "core_api_write_failed".to_string())?;
        let mut line = String::new();
        self.reader
            .read_line(&mut line)
            .map_err(|_| "core_api_read_failed".to_string())?;
        let response: Value = serde_json::from_str(line.trim_end())
            .map_err(|_| "core_api_protocol".to_string())?;
        validate(&response, &request_id)
    }

    pub fn capabilities(&mut self) -> Result<Value, String> {
        self.request("runtime.capabilities", json!({}))
    }
}

fn validate(response: &Value, request_id: &str) -> Result<Value, String> {
    if response.get("api_version").and_then(Value::as_u64) != Some(API_VERSION) {
        return Err("core_api_protocol".into());
    }
    if response.get("request_id").and_then(Value::as_str) != Some(request_id) {
        return Err("core_api_protocol".into());
    }
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        return response
            .get("result")
            .cloned()
            .ok_or_else(|| "core_api_protocol".into());
    }
    Err("core_api_error".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    struct Scripted {
        reader: Cursor<Vec<u8>>,
        writer: Vec<u8>,
    }

    impl Scripted {
        fn new(response: &str) -> Self {
            Self {
                reader: Cursor::new(response.as_bytes().to_vec()),
                writer: Vec::new(),
            }
        }
    }

    fn request(
        reader: &mut Cursor<Vec<u8>>,
        writer: &mut Vec<u8>,
        operation: &str,
    ) -> Result<Value, String> {
        let request_id = "core:1";
        writer.extend_from_slice(
            format!(
                "{{\"api_version\":1,\"request_id\":\"{request_id}\",\"operation\":\"{operation}\",\"params\":{{}}}}\n"
            )
            .as_bytes(),
        );
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        validate(&serde_json::from_str(line.trim_end()).unwrap(), request_id)
    }

    #[test]
    fn accepts_a_correlated_capabilities_result() {
        let mut script = Scripted::new(
            "{\"api_version\":1,\"request_id\":\"core:1\",\"ok\":true,\"result\":{\"api_major\":1}}\n",
        );
        let value = request(&mut script.reader, &mut script.writer, "runtime.capabilities")
            .expect("capabilities result");
        assert_eq!(value["api_major"], 1);
    }

    #[test]
    fn rejects_uncorrelated_or_failed_responses() {
        for response in [
            "{\"api_version\":1,\"request_id\":\"other\",\"ok\":true,\"result\":{}}\n",
            "{\"api_version\":1,\"request_id\":\"core:1\",\"ok\":false,\"error\":{\"code\":\"unavailable\"}}\n",
            "{\"api_version\":2,\"request_id\":\"core:1\",\"ok\":true,\"result\":{}}\n",
        ] {
            let mut script = Scripted::new(response);
            assert!(request(&mut script.reader, &mut script.writer, "runtime.capabilities")
                .is_err());
        }
    }
}
