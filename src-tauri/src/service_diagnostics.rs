//! Bounded, content-free sidecar failure evidence. Raw stderr is never exported.
use serde_json::{json, Value};

const PREFIX: &str = "mesh-chat-diagnostic:";
const MAX_LINE: usize = 4096;
const MAX_RECORDS: usize = 8;

fn choice(value: &Value, allowed: &[&str]) -> String {
    value.as_str().filter(|text| allowed.contains(text)).unwrap_or("unknown").to_string()
}

fn bounded(value: &Value, maximum: u64) -> Value {
    value.as_u64().filter(|number| *number <= maximum).map_or(Value::Null, |number| json!(number))
}

fn clean_record(value: &Value) -> Option<Value> {
    if value["v"].as_u64() != Some(1) { return None; }
    let frames: Vec<Value> = value["frames"].as_array().into_iter().flatten().take(8)
        .filter_map(|frame| {
            let module = choice(&frame["module"], &["__main__", "ipc", "direct_native", "service", "vault", "network", "webrtc_interface", "reconnect_service"]);
            let line = bounded(&frame["line"], 1_000_000);
            if module == "unknown" || line.is_null() { None } else { Some(json!({"module": module, "line": line})) }
        }).collect();
    Some(json!({
        "stage": choice(&value["stage"], &["read_initial", "initialize", "read_command", "dispatch", "write_response", "shutdown", "thread"]),
        "category": choice(&value["category"], &["command_queue_full", "validation_error", "broken_pipe", "end_of_stream", "out_of_memory", "os_error", "value_error", "runtime_error", "unexpected_error"]),
        "last_command": choice(&value["last_command"], &["initialize", "snapshot", "workspace_snapshot", "webrtc_packet", "webrtc_attach", "webrtc_detach", "signal_fetch", "signal_publish", "reconnect_profiles", "reconnect_capabilities_get", "reconnect_capabilities_store", "other"]),
        "pending_commands": bounded(&value["pending_commands"], 1_000_000),
        "queue_capacity": bounded(&value["queue_capacity"], 1_000_000),
        "frames": frames,
    }))
}

#[derive(Default)]
pub(crate) struct Capture {
    pending: Vec<u8>,
    discarding: bool,
    bytes: u64,
    unrecognized: u64,
    records: Vec<Value>,
}

impl Capture {
    pub(crate) fn push(&mut self, bytes: &[u8]) {
        self.bytes = self.bytes.saturating_add(bytes.len() as u64);
        for byte in bytes {
            if *byte == b'\n' { self.finish_line(); }
            else if !self.discarding {
                if self.pending.len() == MAX_LINE { self.pending.clear(); self.discarding = true; }
                else { self.pending.push(*byte); }
            }
        }
    }

    fn finish_line(&mut self) {
        let record = if self.discarding { None } else {
            std::str::from_utf8(&self.pending).ok().and_then(|line| line.trim_end().strip_prefix(PREFIX))
                .and_then(|line| serde_json::from_str::<Value>(line).ok()).and_then(|value| clean_record(&value))
        };
        if let Some(record) = record {
            self.records.push(record);
            if self.records.len() > MAX_RECORDS { self.records.remove(0); }
        } else if self.discarding || !self.pending.is_empty() {
            self.unrecognized = self.unrecognized.saturating_add(1);
        }
        self.pending.clear();
        self.discarding = false;
    }

    pub(crate) fn finish(&mut self) -> Value {
        self.finish_line();
        json!({"stderr_bytes": self.bytes, "unrecognized_stderr_lines": self.unrecognized, "failures": self.records})
    }
}

/// Saved evidence is parsed through the same allowlist as live stderr.
pub(crate) fn saved_exit(bytes: &[u8]) -> Option<Value> {
    if bytes.len() > 16_384 { return None; }
    let raw: Value = serde_json::from_slice(bytes).ok()?;
    let failures: Vec<Value> = raw["failures"].as_array().into_iter().flatten().take(MAX_RECORDS).filter_map(|item| {
        let mut item = item.clone();
        item.as_object_mut()?.insert("v".into(), json!(1));
        clean_record(&item)
    }).collect();
    Some(json!({
        "reason": choice(&raw["reason"], &["protocol_error", "process_event_error", "terminated"]),
        "exit_code": raw["exit_code"].as_i64().filter(|code| (-2147483648..=4294967295).contains(code)),
        "native_version": raw["native_version"].as_str().filter(|text| text.len() <= 32 && text.split('.').count() == 3 && text.split('.').all(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))),
        "build_commit": raw["build_commit"].as_str().filter(|text| text.len() == 40 && text.bytes().all(|byte| byte.is_ascii_hexdigit())),
        "signal": bounded(&raw["signal"], 255), "recorded_at": bounded(&raw["recorded_at"], 9_007_199_254_740_991),
        "uptime_ms": bounded(&raw["uptime_ms"], 9_007_199_254_740_991),
        "pending_requests": bounded(&raw["pending_requests"], 1_000_000),
        "stderr_bytes": bounded(&raw["stderr_bytes"], 9_007_199_254_740_991),
        "unrecognized_stderr_lines": bounded(&raw["unrecognized_stderr_lines"], 9_007_199_254_740_991),
        "failures": failures, "from_previous_app_run": true,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn captures_split_records_and_discards_secrets() {
        let mut capture = Capture::default();
        capture.push(b"private-path-token\nmesh-chat-diag");
        capture.push(b"nostic:{\"v\":1,\"stage\":\"read_command\",\"category\":\"command_queue_full\",\"message\":\"secret\",\"frames\":[{\"module\":\"ipc\",\"line\":50,\"locals\":\"secret\"}]}\n");
        let result = capture.finish();
        assert_eq!(result["failures"][0]["category"], "command_queue_full");
        assert_eq!(result["unrecognized_stderr_lines"], 1);
        assert!(!result.to_string().contains("secret"));
        assert!(!result.to_string().contains("private-path"));
    }
    #[test]
    fn bounds_lines_records_and_saved_files() {
        let mut capture = Capture::default();
        capture.push(&vec![b'x'; 10_000]);
        capture.push(b"\n");
        for _ in 0..20 { capture.push(b"mesh-chat-diagnostic:{\"v\":1,\"stage\":\"secret\"}\n"); }
        let result = capture.finish();
        assert_eq!(result["failures"].as_array().unwrap().len(), MAX_RECORDS);
        assert_eq!(result["failures"][0]["stage"], "unknown");
        assert!(saved_exit(&vec![b'x'; 20_000]).is_none());
        let saved = saved_exit(br#"{"reason":"secret","stderr":"secret","failures":[]}"#).unwrap();
        assert!(!saved.to_string().contains("secret"));
    }
}
