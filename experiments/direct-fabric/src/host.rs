//! App-private session ownership. No renderer commands or identity private keys.
use crate::{attempt::PreparedAttempt, traversal, BoundSocket, Error, SessionKey, MAX_PACKET};
use bytes::Bytes;
use rustls::pki_types::CertificateDer;
use std::{
    collections::HashMap,
    net::SocketAddr,
    sync::{
        atomic::{AtomicU8, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    sync::{mpsc, watch},
    time::Instant,
};

const CAPACITY: usize = 8;
const PACKETS: usize = 32;

pub struct Prepared {
    pub id: u64,
    pub address: SocketAddr,
    pub certificate: Vec<u8>,
}

struct Running {
    cancel: watch::Sender<bool>,
    outgoing: mpsc::Sender<Bytes>,
    incoming: mpsc::Receiver<Bytes>,
    state: Arc<AtomicU8>,
}
impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.cancel.send(true);
    }
}
enum Session {
    Prepared(PreparedAttempt),
    Running(Running),
}
struct Entries {
    next: u64,
    sessions: HashMap<u64, Session>,
}
pub struct Host {
    entries: Mutex<Entries>,
}

impl Host {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            entries: Mutex::new(Entries {
                next: 1,
                sessions: HashMap::new(),
            }),
        })
    }

    pub fn prepare(
        self: &Arc<Self>,
        address: SocketAddr,
        session: [u8; 16],
        generation: u64,
        lifetime: Duration,
    ) -> Result<Prepared, Error> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(300) {
            return Err(Error::Configuration);
        }
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if entries.sessions.len() >= CAPACITY {
            return Err(Error::QueueFull);
        }
        let attempt = PreparedAttempt::new(
            BoundSocket::bind(address)?,
            SessionKey::generate()?,
            session,
            generation,
            lifetime,
        )?;
        let id = entries.next;
        entries.next = id.checked_add(1).ok_or(Error::Closed)?;
        let result = Prepared {
            id,
            address: attempt.address()?,
            certificate: attempt.certificate()?.to_vec(),
        };
        entries.sessions.insert(id, Session::Prepared(attempt));
        let weak = Arc::downgrade(self);
        tokio::spawn(async move {
            tokio::time::sleep(lifetime).await;
            if let Some(host) = weak.upgrade() {
                host.close(id);
            }
        });
        Ok(result)
    }

    pub fn arm(
        &self,
        id: u64,
        session: [u8; 16],
        generation: u64,
        digest: [u8; 32],
    ) -> Result<(), Error> {
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        match entries.sessions.get_mut(&id) {
            Some(Session::Prepared(attempt)) => attempt.start(session, generation, digest),
            _ => Err(Error::Closed),
        }
    }

    pub fn rearm(
        &self,
        id: u64,
        answer: [u8; 32],
        generation: u64,
        ready: [u8; 32],
    ) -> Result<(), Error> {
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        match entries.sessions.get_mut(&id) {
            Some(Session::Prepared(attempt)) => attempt.rearm(answer, generation, ready),
            _ => Err(Error::Closed),
        }
    }

    /// Caller must durably verify the peer certificate, exact chain and scope.
    /// Local/remote destinations are authenticated RNS values, never invite roles.
    pub fn activate(
        &self,
        id: u64,
        certificate: Vec<u8>,
        local: [u8; 16],
        remote: [u8; 16],
        candidates: Vec<traversal::Candidate>,
        remaining: Duration,
    ) -> Result<(), Error> {
        if certificate.is_empty()
            || certificate.len() > 16 * 1024
            || local == remote
            || remaining.is_zero()
            || remaining > Duration::from_secs(60)
        {
            return Err(Error::Configuration);
        }
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if !matches!(entries.sessions.get(&id), Some(Session::Prepared(_))) {
            return Err(Error::Closed);
        }
        let Some(Session::Prepared(attempt)) = entries.sessions.remove(&id) else {
            unreachable!()
        };
        let remaining = remaining.min(attempt.remaining_window()?);
        let peer = attempt.into_peer(CertificateDer::from(certificate))?;
        let (cancel, mut cancelled) = watch::channel(false);
        let (outgoing, mut packets) = mpsc::channel::<Bytes>(PACKETS);
        let (received, incoming) = mpsc::channel::<Bytes>(PACKETS);
        let state = Arc::new(AtomicU8::new(0));
        entries.sessions.insert(
            id,
            Session::Running(Running {
                cancel,
                outgoing,
                incoming,
                state: state.clone(),
            }),
        );
        tokio::spawn(async move {
            let deadline = Instant::now() + remaining;
            let connected = if local < remote {
                traversal::dial(peer, candidates, deadline, cancelled.clone()).await
            } else {
                let result = tokio::select! {
                    biased;
                    _ = cancelled.wait_for(|v| *v) => Err(Error::Closed),
                    _ = tokio::time::sleep_until(deadline) => Err(Error::Timeout),
                    result = peer.accept() => result,
                };
                result.map(|path| (peer, path))
            };
            if let Ok((_peer, path)) = connected {
                state.store(1, Ordering::Release);
                loop {
                    tokio::select! {
                        biased;
                        _ = cancelled.wait_for(|v| *v) => break,
                        packet = packets.recv() => match packet {
                            Some(packet) => { if path.send(packet).is_err() { break; } },
                            None => break,
                        },
                        packet = path.receive() => match packet {
                            Ok(packet) => { if received.try_send(packet).is_err() { break; } },
                            Err(_) => break,
                        },
                    }
                }
            }
            state.store(2, Ordering::Release);
        });
        Ok(())
    }

    pub fn send(&self, id: u64, packets: Vec<Bytes>) -> Result<(), Error> {
        if packets.len() > PACKETS || packets.iter().any(|p| p.is_empty() || p.len() > MAX_PACKET) {
            return Err(Error::DatagramSize);
        }
        let entries = self.entries.lock().map_err(|_| Error::Closed)?;
        let Some(Session::Running(session)) = entries.sessions.get(&id) else {
            return Err(Error::Closed);
        };
        if session.state.load(Ordering::Acquire) != 1 {
            return Err(Error::Closed);
        }
        let permits = session
            .outgoing
            .try_reserve_many(packets.len())
            .map_err(|_| Error::QueueFull)?;
        for (permit, packet) in permits.zip(packets) {
            permit.send(packet);
        }
        Ok(())
    }

    pub fn poll(&self, id: u64) -> Result<(u8, Vec<Bytes>), Error> {
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        let Some(Session::Running(session)) = entries.sessions.get_mut(&id) else {
            return Err(Error::Closed);
        };
        let state = session.state.load(Ordering::Acquire);
        if state == 2 {
            entries.sessions.remove(&id);
            return Ok((2, vec![]));
        }
        let mut packets = vec![];
        while packets.len() < PACKETS {
            match session.incoming.try_recv() {
                Ok(packet) => packets.push(packet),
                Err(_) => break,
            }
        }
        Ok((state, packets))
    }

    pub fn close(&self, id: u64) {
        if let Ok(mut entries) = self.entries.lock() {
            entries.sessions.remove(&id);
        }
    }
    pub fn close_all(&self) {
        if let Ok(mut entries) = self.entries.lock() {
            entries.sessions.clear();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn budget_expiry_and_stale_handles() {
        let host = Host::new();
        let mut ids = vec![];
        for _ in 0..8 {
            ids.push(
                host.prepare(
                    "127.0.0.1:0".parse().unwrap(),
                    [1; 16],
                    1,
                    Duration::from_millis(40),
                )
                .unwrap()
                .id,
            );
        }
        assert!(matches!(
            host.prepare(
                "127.0.0.1:0".parse().unwrap(),
                [1; 16],
                1,
                Duration::from_secs(1)
            ),
            Err(Error::QueueFull)
        ));
        tokio::time::sleep(Duration::from_millis(80)).await;
        let next = host
            .prepare(
                "127.0.0.1:0".parse().unwrap(),
                [1; 16],
                1,
                Duration::from_secs(1),
            )
            .unwrap();
        assert!(next.id > *ids.last().unwrap());
        assert!(host.arm(ids[0], [1; 16], 1, [2; 32]).is_err());
        assert!(host.arm(next.id, [2; 16], 1, [2; 32]).is_err());
        host.arm(next.id, [1; 16], 1, [2; 32]).unwrap();
        host.close_all();
        assert!(host.arm(next.id, [1; 16], 1, [2; 32]).is_err());
    }

    #[tokio::test]
    async fn host_owned_socket_carries_packets_and_cancels() {
        let host = Host::new();
        let a = host
            .prepare(
                "127.0.0.1:0".parse().unwrap(),
                [1; 16],
                1,
                Duration::from_secs(10),
            )
            .unwrap();
        let b = host
            .prepare(
                "127.0.0.1:0".parse().unwrap(),
                [2; 16],
                1,
                Duration::from_secs(10),
            )
            .unwrap();
        host.arm(a.id, [1; 16], 1, [3; 32]).unwrap();
        host.arm(b.id, [2; 16], 1, [3; 32]).unwrap();
        assert!(host.send(a.id, vec![Bytes::from_static(b"early")]).is_err());
        host.activate(
            b.id,
            a.certificate,
            [2; 16],
            [1; 16],
            vec![],
            Duration::from_secs(5),
        )
        .unwrap();
        host.activate(
            a.id,
            b.certificate,
            [1; 16],
            [2; 16],
            vec![traversal::Candidate {
                address: b.address,
                expires: Instant::now() + Duration::from_secs(5),
            }],
            Duration::from_secs(5),
        )
        .unwrap();
        tokio::time::timeout(Duration::from_secs(5), async {
            while host.poll(a.id).unwrap().0 != 1 || host.poll(b.id).unwrap().0 != 1 {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        host.send(a.id, vec![Bytes::from_static(b"private")])
            .unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let (_, packets) = host.poll(b.id).unwrap();
                if !packets.is_empty() {
                    assert_eq!(packets[0], Bytes::from_static(b"private"));
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        host.close(a.id);
        assert!(host.poll(a.id).is_err());
        tokio::time::timeout(Duration::from_secs(2), async {
            while host.poll(b.id).unwrap().0 != 2 {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
    }
}
