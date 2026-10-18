//! Private host/service messages. This module is absent from generate_handler!.
use mesh_direct_proof::{host::Host, traversal::Candidate};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    net::{IpAddr, SocketAddr},
    sync::Arc,
    time::Duration,
};
use uuid::Uuid;

#[derive(Clone)]
pub struct NativeHost(Arc<Host>);
impl Default for NativeHost {
    fn default() -> Self {
        Self(Host::new())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    v: u8,
    #[serde(rename = "type")]
    kind: String,
    id: Uuid,
    request: Operation,
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Operation {
    PreparePath {
        id: u64,
        address: SocketAddr,
    },
    InspectPaths {
        id: u64,
    },
    Prepare {
        address: SocketAddr,
        generation: u64,
        remaining_ms: u64,
    },
    PrepareRecovery {
        address: SocketAddr,
        generation: u64,
        remaining_ms: u64,
    },
    Recover {
        id: u64,
        capsule: String,
        candidates: Vec<SocketAddr>,
        client: bool,
        remaining_ms: u64,
        lifetime_ms: u64,
    },
    RecoveryEvidence {
        id: u64,
    },
    AuthorizeRecovery {
        id: u64,
        token: String,
    },
    Migrate {
        id: u64,
        address: SocketAddr,
    },
    Arm {
        id: u64,
        session: Uuid,
        generation: u64,
        digest: String,
    },
    Rearm {
        id: u64,
        answer: String,
        generation: u64,
        ready: String,
    },
    Activate {
        id: u64,
        certificate: String,
        local: String,
        remote: String,
        candidates: Vec<WireCandidate>,
        remaining_ms: u64,
        client: Option<bool>,
    },
    Send {
        id: u64,
        packets: Vec<String>,
    },
    Poll {
        id: u64,
    },
    Inspect {
        id: u64,
    },
    Close {
        id: u64,
    },
    Reset,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WireCandidate {
    host: IpAddr,
    port: u16,
    remaining_ms: u64,
}

fn unhex(raw: &str, maximum: usize) -> Result<Vec<u8>, ()> {
    if raw.is_empty()
        || raw.len() % 2 != 0
        || raw.len() > maximum * 2
        || !raw
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(());
    }
    (0..raw.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&raw[i..i + 2], 16).map_err(|_| ()))
        .collect()
}
fn fixed<const N: usize>(raw: &str) -> Result<[u8; N], ()> {
    unhex(raw, N)?.try_into().map_err(|_| ())
}
fn hex(raw: &[u8]) -> String {
    raw.iter().map(|b| format!("{b:02x}")).collect()
}

impl NativeHost {
    pub fn close(&self) {
        self.0.close_all();
    }

    pub fn handle(&self, value: Value) -> Value {
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let result = self.execute(value);
        json!({"type":"direct_native_reply", "id":id, "ok":result.is_ok(),
               "result":result.unwrap_or(Value::Null)})
    }

    fn execute(&self, value: Value) -> Result<Value, ()> {
        if serde_json::to_vec(&value).map_err(|_| ())?.len() > 64 * 1024 {
            return Err(());
        }
        let request: Envelope = serde_json::from_value(value).map_err(|_| ())?;
        if request.v != 1 || request.kind != "direct_native" || request.id.is_nil() {
            return Err(());
        }
        match request.request {
            Operation::PreparePath { id, address } => {
                let prepared = self.0.prepare_path(id, address).map_err(|_| ())?;
                Ok(
                    json!({"id":id,"host":prepared.address.ip().to_string(),"port":prepared.address.port(),"certificate":hex(&prepared.certificate)}),
                )
            }
            Operation::InspectPaths { id } => {
                let paths = self.0.inspect_paths(id).map_err(|_| ())?;
                Ok(Value::Array(paths.iter().map(|p| json!({"id":id,"host":p.address.ip().to_string(),"port":p.address.port(),"certificate":hex(&p.certificate)})).collect()))
            }
            Operation::Prepare {
                address,
                generation,
                remaining_ms,
            } => {
                let session = Uuid::new_v4();
                let prepared = self
                    .0
                    .prepare(
                        address,
                        *session.as_bytes(),
                        generation,
                        Duration::from_millis(remaining_ms),
                    )
                    .map_err(|_| ())?;
                Ok(
                    json!({"id":prepared.id, "session":session, "generation":generation,
                    "host":prepared.address.ip().to_string(), "port":prepared.address.port(),
                    "certificate":hex(&prepared.certificate)}),
                )
            }
            Operation::PrepareRecovery {
                address,
                generation,
                remaining_ms,
            } => {
                let session = Uuid::new_v4();
                let p = self
                    .0
                    .prepare_recovery(
                        address,
                        *session.as_bytes(),
                        generation,
                        Duration::from_millis(remaining_ms),
                    )
                    .map_err(|_| ())?;
                Ok(
                    json!({"id":p.id,"session":session,"generation":generation,"host":p.address.ip().to_string(),"port":p.address.port(),"certificate":hex(&p.certificate)}),
                )
            }
            Operation::Recover {
                id,
                capsule,
                candidates,
                client,
                remaining_ms,
                lifetime_ms,
            } => {
                self.0
                    .recover(
                        id,
                        unhex(&capsule, 20 * 1024)?,
                        candidates,
                        client,
                        Duration::from_millis(remaining_ms),
                        Duration::from_millis(lifetime_ms),
                    )
                    .map_err(|_| ())?;
                Ok(Value::Null)
            }
            Operation::RecoveryEvidence { id } => {
                Ok(match self.0.recovery_evidence(id).map_err(|_| ())? {
                    Some(e) => {
                        json!({"certificate":hex(&e.certificate),"capsule":hex(&e.capsule),"token":hex(&e.token)})
                    }
                    None => Value::Null,
                })
            }
            Operation::AuthorizeRecovery { id, token } => {
                self.0
                    .authorize_recovery(id, fixed(&token)?)
                    .map_err(|_| ())?;
                Ok(Value::Null)
            }
            Operation::Migrate { id, address } => {
                let a = self.0.migrate(id, address).map_err(|_| ())?;
                Ok(json!({"host":a.ip().to_string(),"port":a.port()}))
            }
            Operation::Arm {
                id,
                session,
                generation,
                digest,
            } => {
                self.0
                    .arm(id, *session.as_bytes(), generation, fixed(&digest)?)
                    .map_err(|_| ())?;
                Ok(Value::Null)
            }
            Operation::Rearm {
                id,
                answer,
                generation,
                ready,
            } => {
                self.0
                    .rearm(id, fixed(&answer)?, generation, fixed(&ready)?)
                    .map_err(|_| ())?;
                Ok(Value::Null)
            }
            Operation::Activate {
                id,
                certificate,
                local,
                remote,
                candidates,
                remaining_ms,
                client,
            } => {
                if candidates.len() > 8 {
                    return Err(());
                }
                let now = tokio::time::Instant::now();
                let candidates = candidates
                    .into_iter()
                    .map(|c| {
                        if c.remaining_ms > 300_000 || c.port == 0 {
                            return Err(());
                        }
                        Ok(Candidate {
                            address: SocketAddr::new(c.host, c.port),
                            expires: now + Duration::from_millis(c.remaining_ms),
                        })
                    })
                    .collect::<Result<Vec<_>, ()>>()?;
                self.0
                    .activate_with_role(
                        id,
                        unhex(&certificate, 16 * 1024)?,
                        fixed(&local)?,
                        fixed(&remote)?,
                        candidates,
                        Duration::from_millis(remaining_ms),
                        client.unwrap_or(fixed::<16>(&local)? < fixed::<16>(&remote)?),
                    )
                    .map_err(|_| ())?;
                Ok(Value::Null)
            }
            Operation::Send { id, packets } => {
                if packets.len() > 32 {
                    return Err(());
                }
                let packets = packets
                    .iter()
                    .map(|p| unhex(p, 516).map(Into::into))
                    .collect::<Result<Vec<_>, ()>>()?;
                self.0.send(id, packets).map_err(|_| ())?;
                Ok(Value::Null)
            }
            Operation::Poll { id } => {
                let statistics = self.0.statistics(id);
                let (state, packets) = self.0.poll(id).map_err(|_| ())?;
                let mut value = json!({"state":state, "packets":packets.iter().map(|p| hex(p)).collect::<Vec<_>>()});
                if let Some((started, authenticated, elapsed)) = statistics {
                    value["statistics"] = json!({"checks_started":started,"checks_authenticated":authenticated,"elapsed_ms":elapsed});
                }
                Ok(value)
            }
            Operation::Inspect { id } => {
                let prepared = self.0.inspect(id).map_err(|_| ())?;
                Ok(
                    json!({"id":id,"host":prepared.address.ip().to_string(),"port":prepared.address.port(),
                    "certificate":hex(&prepared.certificate)}),
                )
            }
            Operation::Close { id } => {
                self.0.close(id);
                Ok(Value::Null)
            }
            Operation::Reset => {
                self.close();
                Ok(Value::Null)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn private_preparation_rejects_extra_fields_and_stale_handles() {
        let host = NativeHost::default();
        let request = |payload| json!({"v":1,"type":"direct_native","id":Uuid::new_v4().to_string(),"request":payload});
        let rejected = host.handle(request(json!({"op":"prepare","address":"127.0.0.1:0","generation":1,"remaining_ms":1000,"private_key":"x"})));
        assert_eq!(rejected["ok"], false);
        let prepared = host.handle(request(
            json!({"op":"prepare","address":"127.0.0.1:0","generation":1,"remaining_ms":1000}),
        ));
        assert_eq!(prepared["ok"], true);
        assert!(prepared["result"].get("private_key").is_none());
        let id = prepared["result"]["id"].clone();
        host.close();
        assert_eq!(
            host.handle(request(json!({"op":"poll","id":id})))["ok"],
            false
        );
    }
}
