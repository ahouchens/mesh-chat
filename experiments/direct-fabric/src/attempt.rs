//! Native ownership gate. The protected service verifies and persists documents
//! before invoking this API; this module does not grant invitation authority.
use crate::{BoundSocket, Error, Peer, SessionKey};
use rustls::pki_types::CertificateDer;
use std::net::SocketAddr;
use std::time::{Duration, Instant};

const WINDOW: Duration = Duration::from_secs(60);
const MAX_LIFETIME: Duration = Duration::from_secs(300);

/// Non-cloneable owner of the exact socket/key described by one local Answer.
/// Process restart drops this object; durable documents cannot recreate it.
pub struct PreparedAttempt {
    socket: BoundSocket,
    key: SessionKey,
    session: [u8; 16],
    generation: u64,
    expires: Instant,
    answer: Option<[u8; 32]>,
    deadline: Option<Instant>,
    ready: Option<(u64, [u8; 32])>,
}

impl PreparedAttempt {
    pub fn new(
        socket: BoundSocket,
        key: SessionKey,
        session: [u8; 16],
        generation: u64,
        remaining_authorization: Duration,
    ) -> Result<Self, Error> {
        if generation == 0
            || generation > i64::MAX as u64
            || remaining_authorization.is_zero()
            || remaining_authorization > MAX_LIFETIME
        {
            return Err(Error::Configuration);
        }
        Ok(Self {
            socket,
            key,
            session,
            generation,
            expires: Instant::now() + remaining_authorization,
            answer: None,
            deadline: None,
            ready: None,
        })
    }

    pub fn address(&self) -> Result<SocketAddr, Error> {
        self.socket.address()
    }

    pub fn certificate(&self) -> CertificateDer<'static> {
        self.key.certificate()
    }

    /// Call only after the matching locally signed Answer is durably saved.
    pub fn start(
        &mut self,
        session: [u8; 16],
        generation: u64,
        answer: [u8; 32],
    ) -> Result<(), Error> {
        self.start_at(session, generation, answer, Instant::now())
    }

    fn start_at(
        &mut self,
        session: [u8; 16],
        generation: u64,
        answer: [u8; 32],
        now: Instant,
    ) -> Result<(), Error> {
        if session != self.session || generation != self.generation {
            return Err(Error::Identity);
        }
        if now >= self.expires {
            return Err(Error::Timeout);
        }
        if let Some(saved) = self.answer {
            if saved != answer {
                return Err(Error::Identity);
            }
            return self.check_at(now); // Duplicate start never extends a window.
        }
        self.answer = Some(answer);
        self.deadline = Some((now + WINDOW).min(self.expires));
        Ok(())
    }

    /// Only a newly verified, durably accepted Ready can re-arm the same Answer.
    pub fn rearm(
        &mut self,
        answer: [u8; 32],
        ready_generation: u64,
        ready_digest: [u8; 32],
    ) -> Result<(), Error> {
        self.rearm_at(answer, ready_generation, ready_digest, Instant::now())
    }

    fn rearm_at(
        &mut self,
        answer: [u8; 32],
        generation: u64,
        digest: [u8; 32],
        now: Instant,
    ) -> Result<(), Error> {
        if self.answer != Some(answer) || generation == 0 || generation > i64::MAX as u64 {
            return Err(Error::Identity);
        }
        if now >= self.expires {
            return Err(Error::Timeout);
        }
        if let Some((prior, saved)) = self.ready {
            if generation < prior || (generation == prior && digest != saved) {
                return Err(Error::Identity);
            }
            if generation == prior {
                return self.check_at(now); // Replaying Ready cannot keep a socket alive.
            }
        }
        self.ready = Some((generation, digest));
        self.deadline = Some((now + WINDOW).min(self.expires));
        Ok(())
    }

    fn check_at(&self, now: Instant) -> Result<(), Error> {
        if now >= self.expires || self.deadline.is_none_or(|deadline| now >= deadline) {
            Err(Error::Timeout)
        } else {
            Ok(())
        }
    }

    /// Consume ownership once. No socket rebind or separate receiver is created.
    pub fn into_peer(self, expected: CertificateDer<'static>) -> Result<Peer, Error> {
        self.check_at(Instant::now())?;
        Peer::from_bound_socket(self.socket, self.key, expected)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attempt() -> PreparedAttempt {
        PreparedAttempt::new(
            BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap(),
            SessionKey::generate().unwrap(),
            [1; 16],
            1,
            MAX_LIFETIME,
        )
        .unwrap()
    }

    #[test]
    fn exact_answer_and_monotonic_rearm_without_replay_extension() {
        let mut attempt = attempt();
        let now = Instant::now();
        assert_eq!(
            attempt.start_at([2; 16], 1, [3; 32], now),
            Err(Error::Identity)
        );
        assert_eq!(
            attempt.start_at([1; 16], 2, [3; 32], now),
            Err(Error::Identity)
        );
        attempt.start_at([1; 16], 1, [3; 32], now).unwrap();
        assert_eq!(
            attempt.start_at([1; 16], 1, [4; 32], now),
            Err(Error::Identity)
        );
        attempt
            .start_at([1; 16], 1, [3; 32], now + Duration::from_secs(59))
            .unwrap();
        assert_eq!(attempt.check_at(now + WINDOW), Err(Error::Timeout));
        let later = now + Duration::from_secs(70);
        assert_eq!(
            attempt.rearm_at([4; 32], 2, [5; 32], later),
            Err(Error::Identity)
        );
        attempt.rearm_at([3; 32], 2, [5; 32], later).unwrap();
        assert_eq!(
            attempt.rearm_at([3; 32], 2, [6; 32], later),
            Err(Error::Identity)
        );
        assert_eq!(
            attempt.rearm_at([3; 32], 1, [6; 32], later),
            Err(Error::Identity)
        );
        assert_eq!(
            attempt.rearm_at([3; 32], 2, [5; 32], later + WINDOW),
            Err(Error::Timeout)
        );
        attempt
            .rearm_at([3; 32], 3, [6; 32], later + WINDOW)
            .unwrap();
        assert_eq!(
            attempt.rearm_at([3; 32], 4, [7; 32], attempt.expires),
            Err(Error::Timeout)
        );
    }

    #[tokio::test]
    async fn activation_consumes_the_original_socket_and_certificate() {
        let mut prepared = attempt();
        let address = prepared.address().unwrap();
        let cert = prepared.certificate();
        let remote_key = SessionKey::generate().unwrap();
        let expected = remote_key.certificate();
        let remote = Peer::bind("127.0.0.1:0".parse().unwrap(), remote_key, cert).unwrap();
        prepared.start([1; 16], 1, [3; 32]).unwrap();
        let peer = prepared.into_peer(expected).unwrap();
        assert_eq!(peer.address().unwrap(), address);
        let (outbound, inbound) =
            tokio::join!(peer.connect(remote.address().unwrap()), remote.accept());
        outbound
            .unwrap()
            .send(bytes::Bytes::from_static(b"owned socket"))
            .unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), inbound.unwrap().receive())
                .await
                .unwrap()
                .unwrap(),
            bytes::Bytes::from_static(b"owned socket")
        );
    }

    #[test]
    fn restart_cannot_rearm_from_durable_evidence_alone() {
        let mut fresh = attempt();
        assert_eq!(fresh.rearm([3; 32], 2, [5; 32]), Err(Error::Identity));
    }
}
