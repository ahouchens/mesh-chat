//! Private transport admission, independent of windows and service dispatch.
use serde_json::Value;
use std::collections::{HashSet, VecDeque};

pub struct Binding {
    pid: u32,
    label: String,
    token: String,
    epoch: Option<String>,
    sequence: u64,
    requests: VecDeque<Value>,
    pending: HashSet<String>,
    retired: bool,
    polls: u64,
}

impl Binding {
    pub fn new(pid: u32, label: String, token: String) -> Self {
        Self {
            pid,
            label,
            token,
            epoch: None,
            sequence: 0,
            requests: VecDeque::new(),
            pending: HashSet::new(),
            retired: false,
            polls: 0,
        }
    }

    pub fn pid(&self) -> u32 {
        self.pid
    }
    #[cfg(feature = "transport-qualification")]
    pub fn diagnostics(&self) -> Value {
        serde_json::json!({"registered":true, "polls":self.polls,
            "pending":self.pending.len(), "queued":self.requests.len()})
    }
    pub fn fault(&self) -> Option<Value> {
        self.epoch.as_ref().map(|epoch| {
            serde_json::json!({
                "v": 1, "type": "desktop_transport_fault", "epoch": epoch
            })
        })
    }

    pub fn admit(&mut self, pid: u32, frame: Value) -> Result<(), &'static str> {
        if pid != self.pid || self.retired {
            return Err("transport_retired");
        }
        if !fields(&frame, &["v", "type", "epoch", "id", "request"])
            || frame["v"].as_u64() != Some(1)
            || frame["type"] != "desktop_transport"
            || !bounded(&frame, 256 * 1024)
        {
            return Err("invalid_transport_frame");
        }
        let epoch = frame["epoch"]
            .as_str()
            .filter(|s| {
                s.len() == 32
                    && s.bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            })
            .ok_or("invalid_transport_epoch")?;
        if self
            .epoch
            .as_deref()
            .is_some_and(|current| current != epoch)
        {
            return Err("transport_epoch_changed");
        }
        let id = frame["id"].as_str().ok_or("invalid_transport_sequence")?;
        let sequence = id
            .parse::<u64>()
            .map_err(|_| "invalid_transport_sequence")?;
        if sequence <= self.sequence || sequence.to_string() != id {
            return Err("transport_replay");
        }
        let operation = frame["request"]["op"]
            .as_str()
            .ok_or("invalid_transport_operation")?;
        if !matches!(
            operation,
            "createOffer"
                | "acceptOffer"
                | "applyAnswer"
                | "inspect"
                | "inventory"
                | "send"
                | "sendControl"
                | "close"
                | "reset"
        ) {
            return Err("invalid_transport_operation");
        }
        if operation == "reset" {
            if !fields(&frame["request"], &["op"]) {
                return Err("invalid_transport_operation");
            }
            self.requests.clear();
            self.pending.clear();
            self.retired = true;
        } else if self.pending.len() >= 16 || self.requests.len() >= 16 {
            return Err("transport_capacity");
        }
        self.epoch = Some(epoch.to_owned());
        self.sequence = sequence;
        self.pending.insert(id.to_owned());
        self.requests.push_back(frame);
        Ok(())
    }

    pub fn exchange(
        &mut self,
        pid: u32,
        label: &str,
        token: &str,
        incoming: Vec<Value>,
    ) -> Result<(Vec<Value>, Vec<Value>), &'static str> {
        // Authentication errors cannot retire the legitimate host or consume its queue.
        if pid != self.pid || label != self.label || token != self.token {
            return Err("transport_caller_denied");
        }
        self.polls = self.polls.saturating_add(1);
        if incoming.len() > 64 || !bounded(&incoming, 2 * 1024 * 1024) {
            return Err("transport_frame_budget");
        }
        for frame in &incoming {
            self.validate_reply(frame)?;
        }
        let accepted = incoming
            .into_iter()
            .filter(|frame| {
                frame["type"] == "desktop_transport_event"
                    || frame["id"]
                        .as_str()
                        .is_some_and(|id| self.pending.remove(id))
            })
            .collect();
        Ok((accepted, self.requests.drain(..).collect()))
    }

    fn validate_reply(&self, frame: &Value) -> Result<(), &'static str> {
        if frame["v"].as_u64() != Some(1)
            || frame["epoch"].as_str() != self.epoch.as_deref()
            || self.epoch.is_none()
            || !bounded(frame, 256 * 1024)
        {
            return Err("invalid_transport_frame");
        }
        if frame["type"] == "desktop_transport_reply"
            && fields(frame, &["v", "type", "epoch", "id", "ok", "result"])
            && frame["id"]
                .as_str()
                .is_some_and(|id| !id.is_empty() && id.len() <= 20)
            && frame["ok"].as_bool().is_some()
            && (frame["ok"] == true || frame["result"].is_null())
        {
            return Ok(());
        }
        if frame["type"] == "desktop_transport_event"
            && fields(frame, &["v", "type", "epoch", "event", "resource", "data"])
            && frame["event"].as_str().is_some_and(|event| {
                matches!(
                    event,
                    "open"
                        | "closed"
                        | "ice"
                        | "channel"
                        | "signaling"
                        | "gathering"
                        | "message"
                        | "control"
                )
            })
            && frame["resource"].as_str().is_some_and(|id| {
                !id.is_empty()
                    && id.len() <= 128
                    && id
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
            })
            && frame["data"].as_str().is_some_and(|data| {
                data.len()
                    <= if frame["event"] == "message" {
                        1500
                    } else {
                        90000
                    }
            })
        {
            return Ok(());
        }
        Err("invalid_transport_frame")
    }
}

fn fields(value: &Value, names: &[&str]) -> bool {
    value.as_object().is_some_and(|object| {
        object.len() == names.len() && names.iter().all(|name| object.contains_key(*name))
    })
}

fn bounded(value: &impl serde::Serialize, limit: usize) -> bool {
    serde_json::to_vec(value).is_ok_and(|encoded| encoded.len() <= limit)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    const EPOCH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    fn binding() -> Binding {
        Binding::new(42, "private-window".into(), "private-token".into())
    }
    fn request(id: u64, op: &str) -> Value {
        json!({"v":1,"type":"desktop_transport","epoch":EPOCH,"id":id.to_string(),"request":{"op":op}})
    }
    fn response(id: u64) -> Value {
        json!({"v":1,"type":"desktop_transport_reply","epoch":EPOCH,"id":id.to_string(),"ok":true,"result":null})
    }
    fn exchange(host: &mut Binding, incoming: Vec<Value>) -> (Vec<Value>, Vec<Value>) {
        host.exchange(42, "private-window", "private-token", incoming)
            .unwrap()
    }

    #[test]
    fn inventory_uses_the_same_private_process_and_request_fences() {
        let mut host = binding();
        assert!(host.admit(99, request(1, "inventory")).is_err());
        host.admit(42, request(1, "inventory")).unwrap();
        assert!(host.admit(42, request(1, "inventory")).is_err());
        assert_eq!(exchange(&mut host, vec![]).1, vec![request(1, "inventory")]);
        let mut reply = response(1);
        reply["result"] = json!({"v":1,"adapter_epoch":EPOCH,"resources":[]});
        assert_eq!(exchange(&mut host, vec![reply.clone()]).0, vec![reply]);
    }

    #[test]
    fn only_the_exact_process_window_and_capability_can_drain_or_reply() {
        let mut host = binding();
        host.admit(42, request(1, "inspect")).unwrap();
        for (pid, label, token) in [
            (99, "private-window", "private-token"),
            (42, "main", "private-token"),
            (42, "private-window", "forged"),
        ] {
            assert_eq!(
                host.exchange(pid, label, token, vec![response(1)])
                    .unwrap_err(),
                "transport_caller_denied"
            );
        }
        assert_eq!(exchange(&mut host, vec![]).1, vec![request(1, "inspect")]);
        assert_eq!(exchange(&mut host, vec![response(1)]).0, vec![response(1)]);
        let (replies, commands) = exchange(&mut host, vec![response(1)]);
        assert!(replies.is_empty());
        assert!(commands.is_empty());
    }

    #[test]
    fn stale_service_epochs_and_replayed_sequences_cannot_allocate() {
        let mut host = binding();
        host.admit(42, request(2, "createOffer")).unwrap();
        assert!(host.admit(99, request(3, "createOffer")).is_err());
        assert!(host.admit(42, request(2, "createOffer")).is_err());
        assert!(host.admit(42, request(1, "close")).is_err());
        let mut foreign = request(3, "createOffer");
        foreign["epoch"] = json!("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
        assert!(host.admit(42, foreign).is_err());
        assert_eq!(exchange(&mut host, vec![]).1.len(), 1);
    }

    #[test]
    fn pending_work_stays_bounded_after_the_window_drains_and_reset_has_reserved_admission() {
        let mut host = binding();
        for id in 1..=16 {
            host.admit(42, request(id, "inspect")).unwrap();
        }
        assert_eq!(exchange(&mut host, vec![]).1.len(), 16);
        assert_eq!(
            host.admit(42, request(17, "inspect")).unwrap_err(),
            "transport_capacity"
        );
        host.admit(42, request(18, "reset")).unwrap();
        assert!(host.admit(42, request(19, "createOffer")).is_err());
        let (replies, commands) = exchange(&mut host, vec![response(1)]);
        assert!(replies.is_empty());
        assert_eq!(commands, vec![request(18, "reset")]);
        assert_eq!(exchange(&mut host, vec![]).1.len(), 0);
    }

    #[test]
    fn malformed_and_oversized_frames_cannot_consume_valid_pending_replies() {
        let mut host = binding();
        host.admit(42, request(1, "inspect")).unwrap();
        let mut invalid = response(1);
        invalid["ok"] = json!(1);
        assert!(host
            .exchange(42, "private-window", "private-token", vec![invalid])
            .is_err());
        assert!(host
            .exchange(42, "private-window", "private-token", vec![response(1); 65])
            .is_err());
        let mut huge = response(1);
        huge["result"] = json!("x".repeat(256 * 1024));
        assert!(host
            .exchange(42, "private-window", "private-token", vec![huge])
            .is_err());
        assert_eq!(exchange(&mut host, vec![response(1)]).0.len(), 1);
    }
}
