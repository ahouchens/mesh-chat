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
    statistics: Arc<traversal::Statistics>,
    started: Instant,
    reserved_sockets: usize,
}
impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.cancel.send(true);
    }
}
enum Session {
    Prepared(PreparedAttempt),
    Running(Running),
    Recovery(crate::recovery::Running),
}
struct Entries {
    next: u64,
    sessions: HashMap<u64, Session>,
    extra: HashMap<u64, Vec<PreparedAttempt>>,
}
pub struct Host {
    entries: Mutex<Entries>,
}

fn socket_count(entries: &Entries) -> usize {
    entries
        .sessions
        .values()
        .map(|session| match session {
            Session::Running(running) => running.reserved_sockets,
            _ => 1,
        })
        .sum::<usize>()
        + entries.extra.values().map(Vec::len).sum::<usize>()
}

impl Host {
    pub fn prepare_path(&self, id: u64, address: SocketAddr) -> Result<Prepared, Error> {
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if socket_count(&entries) >= CAPACITY || entries.extra.get(&id).map_or(0, Vec::len) >= 3 {
            return Err(Error::QueueFull);
        }
        let Some(Session::Prepared(first)) = entries.sessions.get(&id) else {
            return Err(Error::Closed);
        };
        let extra = first.additional_socket(address)?;
        let prepared = Prepared {
            id,
            address: extra.address()?,
            certificate: extra.certificate()?.to_vec(),
        };
        entries.extra.entry(id).or_default().push(extra);
        Ok(prepared)
    }

    pub fn inspect_paths(&self, id: u64) -> Result<Vec<Prepared>, Error> {
        let first = self.inspect(id)?;
        let entries = self.entries.lock().map_err(|_| Error::Closed)?;
        let mut result = vec![first];
        for extra in entries.extra.get(&id).into_iter().flatten() {
            result.push(Prepared {
                id,
                address: extra.address()?,
                certificate: extra.certificate()?.to_vec(),
            });
        }
        Ok(result)
    }
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            entries: Mutex::new(Entries {
                next: 1,
                sessions: HashMap::new(),
                extra: HashMap::new(),
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
        if lifetime > Duration::from_secs(300) {
            return Err(Error::Configuration);
        }
        self.prepare_recovery(address, session, generation, lifetime)
    }

    pub fn prepare_recovery(
        self: &Arc<Self>,
        address: SocketAddr,
        session: [u8; 16],
        generation: u64,
        lifetime: Duration,
    ) -> Result<Prepared, Error> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(3600) {
            return Err(Error::Configuration);
        }
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if socket_count(&entries) >= CAPACITY {
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
                if let Ok(mut entries) = host.entries.lock() {
                    entries.sessions.remove(&id);
                    entries.extra.remove(&id);
                }
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
        if let Some(extra) = entries.extra.get_mut(&id) {
            for attempt in extra {
                attempt.start(session, generation, digest)?;
            }
        }
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
        if let Some(extra) = entries.extra.get_mut(&id) {
            for attempt in extra {
                attempt.rearm(answer, generation, ready)?;
            }
        }
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
        self.activate_with_role(
            id,
            certificate,
            local,
            remote,
            candidates,
            remaining,
            local < remote,
        )
    }

    /// Version-2 callers derive this role from both authenticated candidate sets.
    /// With one public side, the side without a candidate must be the client.
    pub fn activate_with_role(
        &self,
        id: u64,
        certificate: Vec<u8>,
        local: [u8; 16],
        remote: [u8; 16],
        candidates: Vec<traversal::Candidate>,
        remaining: Duration,
        client: bool,
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
        let extra_paths = entries.extra.remove(&id).unwrap_or_default();
        let remaining = remaining.min(attempt.remaining_window()?);
        let certificate = CertificateDer::from(certificate);
        let mut peers = vec![attempt.into_peer(certificate.clone())?];
        for extra in extra_paths {
            peers.push(extra.into_peer(certificate.clone())?);
        }
        let reserved_sockets = peers.len();
        let (cancel, mut cancelled) = watch::channel(false);
        let (outgoing, mut packets) = mpsc::channel::<Bytes>(PACKETS);
        let (received, incoming) = mpsc::channel::<Bytes>(PACKETS);
        let state = Arc::new(AtomicU8::new(0));
        let statistics = Arc::new(traversal::Statistics::default());
        entries.sessions.insert(
            id,
            Session::Running(Running {
                cancel,
                outgoing,
                incoming,
                state: state.clone(),
                statistics: statistics.clone(),
                started: Instant::now(),
                reserved_sockets,
            }),
        );
        tokio::spawn(async move {
            let deadline = Instant::now() + remaining;
            let connected = if peers.len() > 1 {
                crate::paths::connect(
                    peers,
                    candidates,
                    client,
                    deadline,
                    cancelled.clone(),
                    statistics,
                )
                .await
            } else {
                let peer = peers.remove(0);
                let result = if client {
                    traversal::dial_measured(
                        peer,
                        candidates,
                        deadline,
                        cancelled.clone(),
                        statistics,
                    )
                    .await
                } else {
                    traversal::listen_measured(
                        peer,
                        candidates,
                        deadline,
                        cancelled.clone(),
                        statistics,
                    )
                    .await
                };
                result.map(|(peer, path)| (Arc::new(peer), path))
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
                            Ok(packet) => match received.try_send(packet) {
                                Ok(()) | Err(mpsc::error::TrySendError::Full(_)) => {},
                                Err(mpsc::error::TrySendError::Closed(_)) => break,
                            },
                            Err(_) => break,
                        },
                    }
                }
            }
            state.store(2, Ordering::Release);
        });
        Ok(())
    }

    pub fn recover(
        &self,
        id: u64,
        capsule: Vec<u8>,
        candidates: Vec<SocketAddr>,
        client: bool,
        attempt: Duration,
        lifetime: Duration,
    ) -> Result<(), Error> {
        if attempt.is_zero()
            || attempt > Duration::from_secs(60)
            || lifetime < attempt
            || lifetime > Duration::from_secs(3600)
        {
            return Err(Error::Configuration);
        }
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        // Recovery currently owns one socket. Never silently discard advertised
        // alternatives if a caller accidentally passes an initial setup group.
        if entries
            .extra
            .get(&id)
            .is_some_and(|paths| !paths.is_empty())
        {
            return Err(Error::Configuration);
        }
        if !matches!(entries.sessions.get(&id), Some(Session::Prepared(_))) {
            return Err(Error::Closed);
        }
        let Some(Session::Prepared(prepared)) = entries.sessions.remove(&id) else {
            unreachable!()
        };
        entries.extra.remove(&id);
        let attempt = attempt.min(prepared.remaining_window()?);
        let (bound, key) = prepared.into_recovery_parts()?;
        let running = crate::recovery::Running::start(
            bound, key, capsule, candidates, client, attempt, lifetime,
        )?;
        entries.sessions.insert(id, Session::Recovery(running));
        Ok(())
    }
    pub fn recovery_evidence(&self, id: u64) -> Result<Option<crate::recovery::Evidence>, Error> {
        let entries = self.entries.lock().map_err(|_| Error::Closed)?;
        let Some(Session::Recovery(running)) = entries.sessions.get(&id) else {
            return Err(Error::Closed);
        };
        let evidence = running.evidence.lock().map_err(|_| Error::Closed)?;
        Ok(evidence.as_ref().map(|e| crate::recovery::Evidence {
            certificate: e.certificate.clone(),
            capsule: e.capsule.clone(),
            token: e.token,
        }))
    }
    pub fn authorize_recovery(&self, id: u64, token: [u8; 32]) -> Result<(), Error> {
        let entries = self.entries.lock().map_err(|_| Error::Closed)?;
        let Some(Session::Recovery(running)) = entries.sessions.get(&id) else {
            return Err(Error::Closed);
        };
        running.authorize(token)
    }
    pub fn migrate(&self, id: u64, address: SocketAddr) -> Result<SocketAddr, Error> {
        let entries = self.entries.lock().map_err(|_| Error::Closed)?;
        let Some(Session::Recovery(running)) = entries.sessions.get(&id) else {
            return Err(Error::Closed);
        };
        running.migrate(BoundSocket::bind(address)?)?;
        running.address()
    }
    pub fn send(&self, id: u64, packets: Vec<Bytes>) -> Result<(), Error> {
        if packets.len() > PACKETS || packets.iter().any(|p| p.is_empty() || p.len() > MAX_PACKET) {
            return Err(Error::DatagramSize);
        }
        let entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if let Some(Session::Recovery(session)) = entries.sessions.get(&id) {
            return session.send(packets);
        }
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

    pub fn statistics(&self, id: u64) -> Option<(u64, u64, u64)> {
        let entries = self.entries.lock().ok()?;
        if let Some(Session::Running(session)) = entries.sessions.get(&id) {
            Some((
                session.statistics.started.load(Ordering::Relaxed),
                session.statistics.authenticated.load(Ordering::Relaxed),
                session.started.elapsed().as_millis().min(u64::MAX as u128) as u64,
            ))
        } else {
            None
        }
    }

    pub fn poll(&self, id: u64) -> Result<(u8, Vec<Bytes>), Error> {
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if let Some(Session::Recovery(session)) = entries.sessions.get_mut(&id) {
            let result = session.poll();
            if result.0 == 2 {
                entries.sessions.remove(&id);
            }
            return Ok(result);
        }
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
            entries.extra.remove(&id);
        }
    }

    pub fn inspect(&self, id: u64) -> Result<Prepared, Error> {
        let mut entries = self.entries.lock().map_err(|_| Error::Closed)?;
        if let Some(Session::Recovery(session)) = entries.sessions.get(&id) {
            if session.state.load(Ordering::Acquire) == 2 {
                entries.sessions.remove(&id);
                return Err(Error::Closed);
            }
            return Ok(Prepared {
                id,
                address: session.address()?,
                certificate: session.certificate.clone(),
            });
        }
        let Some(Session::Prepared(attempt)) = entries.sessions.get_mut(&id) else {
            return Err(Error::Closed);
        };
        if attempt.expire() {
            entries.sessions.remove(&id);
            entries.extra.remove(&id);
            return Err(Error::Timeout);
        }
        Ok(Prepared {
            id,
            address: attempt.address()?,
            certificate: attempt.certificate()?.to_vec(),
        })
    }
    pub fn close_all(&self) {
        if let Ok(mut entries) = self.entries.lock() {
            entries.sessions.clear();
            entries.extra.clear();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn route_group_shares_certificate_and_releases_all_sockets_on_cancel() {
        let host = Host::new();
        let first = host
            .prepare(
                "127.0.0.1:0".parse().unwrap(),
                [3; 16],
                1,
                Duration::from_secs(30),
            )
            .unwrap();
        let mut addresses = vec![first.address];
        for _ in 0..3 {
            let extra = host
                .prepare_path(first.id, "127.0.0.1:0".parse().unwrap())
                .unwrap();
            assert_eq!(extra.certificate, first.certificate);
            addresses.push(extra.address);
        }
        assert!(host
            .prepare_path(first.id, "127.0.0.1:0".parse().unwrap())
            .is_err());
        assert_eq!(host.inspect_paths(first.id).unwrap().len(), 4);
        host.arm(first.id, [3; 16], 1, [4; 32]).unwrap();
        assert!(host
            .prepare_path(first.id, "127.0.0.1:0".parse().unwrap())
            .is_err());
        host.close(first.id);
        for address in addresses {
            assert!(std::net::UdpSocket::bind(address).is_ok());
        }
    }
    #[tokio::test]
    async fn recovery_cannot_extend_prepared_socket_ownership() {
        let host = Host::new();
        let prepared = host
            .prepare_recovery(
                "127.0.0.1:0".parse().unwrap(),
                [1; 16],
                1,
                Duration::from_millis(200),
            )
            .unwrap();
        host.arm(prepared.id, [1; 16], 1, [2; 32]).unwrap();
        host.recover(
            prepared.id,
            vec![1],
            vec![],
            false,
            Duration::from_secs(1),
            Duration::from_secs(2),
        )
        .unwrap();
        tokio::time::sleep(Duration::from_millis(300)).await;
        assert!(host.inspect(prepared.id).is_err());
        assert!(host.poll(prepared.id).is_err());
    }

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
        host_socket(false).await;
    }

    #[tokio::test]
    async fn unhosted_v2_peer_can_dial_despite_destination_ordering() {
        host_socket(true).await;
    }

    async fn host_socket(reverse_destinations: bool) {
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
        host.activate_with_role(
            b.id,
            a.certificate,
            if reverse_destinations {
                [1; 16]
            } else {
                [2; 16]
            },
            if reverse_destinations {
                [2; 16]
            } else {
                [1; 16]
            },
            vec![],
            Duration::from_secs(5),
            false,
        )
        .unwrap();
        host.activate_with_role(
            a.id,
            b.certificate,
            if reverse_destinations {
                [2; 16]
            } else {
                [1; 16]
            },
            if reverse_destinations {
                [1; 16]
            } else {
                [2; 16]
            },
            vec![traversal::Candidate {
                address: b.address,
                expires: Instant::now() + Duration::from_secs(5),
            }],
            Duration::from_secs(5),
            true,
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
