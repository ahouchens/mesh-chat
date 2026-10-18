//! Coordinated QUIC checks on the retained, service-authorized socket.
//! Quinn is the sole receiver. No external discovery or custom UDP frames.
use crate::{Error, Path, Peer};
use std::{
    collections::HashSet,
    net::SocketAddr,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, OnceLock,
    },
    time::Duration,
};
use tokio::{sync::watch, time::Instant};

pub struct Candidate {
    pub address: SocketAddr,
    /// Converted once from verified document validity by the protected caller.
    pub expires: Instant,
}

#[derive(Default)]
pub struct Statistics {
    pub started: AtomicU64,
    pub authenticated: AtomicU64,
}

const CHECK_SLICE: Duration = Duration::from_millis(1500);
const CHECK_INTERVAL: Duration = Duration::from_millis(500);

/// Shared by initial setup and recovery: at most eight native handshake starts
/// per second in this process. Reservations disappear with the process; they do
/// not grant authority or extend any caller deadline.
pub async fn pace(deadline: Instant) -> Result<(), Error> {
    static NEXT: OnceLock<tokio::sync::Mutex<Instant>> = OnceLock::new();
    let when = {
        let mut next = NEXT
            .get_or_init(|| tokio::sync::Mutex::new(Instant::now()))
            .lock()
            .await;
        let when = (*next).max(Instant::now());
        if when >= deadline {
            return Err(Error::Timeout);
        }
        *next = when + Duration::from_millis(125);
        when
    };
    tokio::time::sleep_until(when).await;
    Ok(())
}

pub(crate) fn validate(candidates: &[Candidate], allow_empty: bool) -> Result<(), Error> {
    if (!allow_empty && candidates.is_empty()) || candidates.len() > 8 {
        return Err(Error::Configuration);
    }
    let mut seen = HashSet::new();
    for candidate in candidates {
        if candidate.address.port() == 0
            || candidate.address.ip().is_unspecified()
            || candidate.address.ip().is_multicast()
            || !seen.insert(candidate.address)
        {
            return Err(Error::Configuration);
        }
    }
    Ok(())
}

async fn checks(
    peer: &Peer,
    candidates: &[Candidate],
    deadline: Instant,
    statistics: &Statistics,
) -> Result<Path, Error> {
    let mut count = 0;
    while count < 64 && Instant::now() < deadline {
        let mut attempted = false;
        for candidate in candidates {
            let start = Instant::now();
            let until = deadline.min(candidate.expires);
            if start >= until {
                continue;
            }
            pace(until).await?;
            attempted = true;
            count += 1;
            statistics.started.fetch_add(1, Ordering::Relaxed);
            if let Ok(Ok(path)) = tokio::time::timeout_at(
                until.min(start + CHECK_SLICE),
                peer.connect(candidate.address),
            )
            .await
            {
                statistics.authenticated.fetch_add(1, Ordering::Relaxed);
                return Ok(path);
            }
            if count == 64 {
                return Err(Error::Timeout);
            }
            tokio::time::sleep_until(until.min(start + CHECK_INTERVAL)).await;
        }
        if !attempted {
            break;
        }
    }
    Err(Error::Timeout)
}

/// Consumes the endpoint so cancellation, caller abandonment, and exhaustion
/// release the socket. Success returns that same owner with its authenticated
/// path. Only the deterministic QUIC client may invoke this operation.
pub async fn dial(
    peer: Peer,
    candidates: Vec<Candidate>,
    deadline: Instant,
    cancelled: watch::Receiver<bool>,
) -> Result<(Peer, Path), Error> {
    dial_measured(
        peer,
        candidates,
        deadline,
        cancelled,
        Arc::new(Statistics::default()),
    )
    .await
}

pub async fn dial_measured(
    peer: Peer,
    candidates: Vec<Candidate>,
    deadline: Instant,
    mut cancelled: watch::Receiver<bool>,
    statistics: Arc<Statistics>,
) -> Result<(Peer, Path), Error> {
    let now = Instant::now();
    if deadline <= now {
        return Err(Error::Timeout);
    }
    if deadline - now > Duration::from_secs(60) {
        return Err(Error::Configuration);
    }
    validate(&candidates, false)?;
    // The deterministic client never selects the server's auxiliary check.
    // It authenticates then closes it without exposing any application packets.
    let auxiliary = async {
        for _ in 0..64 {
            if let Ok(path) = peer.accept().await {
                statistics.authenticated.fetch_add(1, Ordering::Relaxed);
                path.close();
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        std::future::pending::<()>().await;
    };
    let result = tokio::select! {
        biased;
        // A dropped service authority channel also cancels the endpoint.
        _ = cancelled.wait_for(|value| *value) => Err(Error::Closed),
        _ = tokio::time::sleep_until(deadline) => Err(Error::Timeout),
        result = checks(&peer, &candidates, deadline, &statistics) => result,
        _ = auxiliary => Err(Error::Timeout),
    };
    result.map(|path| (peer, path))
}

/// Keep the server available throughout the same bounded overlap window.
/// A silent interval or an unauthenticated handshake does not consume the window.
pub async fn listen(
    peer: Peer,
    deadline: Instant,
    cancelled: watch::Receiver<bool>,
) -> Result<(Peer, Path), Error> {
    listen_with_checks(peer, vec![], deadline, cancelled).await
}

/// The selected server also sends bounded outbound checks to known peer tuples.
/// A peer with no advertised tuple is learned by the authenticated incoming QUIC
/// connection itself; we never guess or export that destination-specific address.
pub async fn listen_with_checks(
    peer: Peer,
    candidates: Vec<Candidate>,
    deadline: Instant,
    cancelled: watch::Receiver<bool>,
) -> Result<(Peer, Path), Error> {
    listen_measured(
        peer,
        candidates,
        deadline,
        cancelled,
        Arc::new(Statistics::default()),
    )
    .await
}

pub async fn listen_measured(
    peer: Peer,
    candidates: Vec<Candidate>,
    deadline: Instant,
    mut cancelled: watch::Receiver<bool>,
    statistics: Arc<Statistics>,
) -> Result<(Peer, Path), Error> {
    let now = Instant::now();
    if deadline <= now {
        return Err(Error::Timeout);
    }
    if deadline - now > Duration::from_secs(60) {
        return Err(Error::Configuration);
    }
    validate(&candidates, true)?;
    let outgoing = async {
        // One successful auxiliary connection is enough to open this filter.
        // Only the incoming deterministic connection may carry application data.
        if let Ok(path) = checks(&peer, &candidates, deadline, &statistics).await {
            path.close();
        }
        std::future::pending::<()>().await;
    };
    let attempts = async {
        for _ in 0..64 {
            if let Ok(path) = peer.accept().await {
                statistics.authenticated.fetch_add(1, Ordering::Relaxed);
                return Ok(path);
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        Err(Error::Timeout)
    };
    let result = tokio::select! {
        biased;
        _ = cancelled.wait_for(|value| *value) => Err(Error::Closed),
        _ = tokio::time::sleep_until(deadline) => Err(Error::Timeout),
        result = attempts => result,
        _ = outgoing => Err(Error::Timeout),
    };
    result.map(|path| (peer, path))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SessionKey;

    fn pair() -> (Peer, Peer) {
        let a = SessionKey::generate().unwrap();
        let b = SessionKey::generate().unwrap();
        let ac = a.certificate();
        let bc = b.certificate();
        (
            Peer::bind("127.0.0.1:0".parse().unwrap(), a, bc).unwrap(),
            Peer::bind("127.0.0.1:0".parse().unwrap(), b, ac).unwrap(),
        )
    }

    #[tokio::test]
    async fn silent_first_candidate_does_not_starve_live_alternative() {
        let (a, b) = pair();
        let silent = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        let (_cancel, rx) = watch::channel(false);
        let end = Instant::now() + Duration::from_secs(8);
        let candidates = vec![
            Candidate {
                address: silent.local_addr().unwrap(),
                expires: end,
            },
            Candidate {
                address: b.address().unwrap(),
                expires: end,
            },
        ];
        let (out, incoming) = tokio::time::timeout(Duration::from_secs(5), async {
            tokio::join!(dial(a, candidates, end, rx), b.accept())
        })
        .await
        .unwrap();
        assert!(out.is_ok());
        assert!(incoming.is_ok());
    }

    #[tokio::test]
    async fn simultaneous_checks_select_only_the_deterministic_application_path() {
        let (a, b) = pair();
        let aa = a.address().unwrap();
        let ba = b.address().unwrap();
        let (_cancel, rx) = watch::channel(false);
        let end = Instant::now() + Duration::from_secs(8);
        let (out, incoming) = tokio::join!(
            dial(
                a,
                vec![Candidate {
                    address: ba,
                    expires: end
                }],
                end,
                rx.clone()
            ),
            listen_with_checks(
                b,
                vec![Candidate {
                    address: aa,
                    expires: end
                }],
                end,
                rx
            )
        );
        let (a, outgoing) = out.unwrap();
        let (b, incoming) = incoming.unwrap();
        assert_eq!(a.address().unwrap(), aa);
        assert_eq!(b.address().unwrap(), ba);
        outgoing
            .send(bytes::Bytes::from_static(b"selected"))
            .unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), incoming.receive())
                .await
                .unwrap()
                .unwrap(),
            bytes::Bytes::from_static(b"selected")
        );
        incoming
            .send(bytes::Bytes::from_static(b"receipt"))
            .unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), outgoing.receive())
                .await
                .unwrap()
                .unwrap(),
            bytes::Bytes::from_static(b"receipt")
        );
    }

    #[tokio::test]
    async fn delayed_email_activation_keeps_exact_socket_until_overlap() {
        let (a, b) = pair();
        let original = a.address().unwrap();
        let target = b.address().unwrap();
        let (_cancel, rx) = watch::channel(false);
        let end = Instant::now() + Duration::from_secs(15);
        let accepting = async {
            tokio::time::sleep(Duration::from_secs(6)).await;
            listen(b, end, rx.clone()).await
        };
        let (out, incoming) = tokio::join!(
            dial(
                a,
                vec![Candidate {
                    address: target,
                    expires: end
                }],
                end,
                rx.clone()
            ),
            accepting
        );
        assert_eq!(out.unwrap().0.address().unwrap(), original);
        assert!(incoming.is_ok());
    }

    #[tokio::test]
    async fn stale_candidate_skipped_and_same_socket_delivers() {
        let (a, b) = pair();
        let original = a.address().unwrap();
        let (_cancel, rx) = watch::channel(false);
        let end = Instant::now() + Duration::from_secs(10);
        let candidates = vec![
            Candidate {
                address: "127.0.0.1:1".parse().unwrap(),
                expires: Instant::now(),
            },
            Candidate {
                address: b.address().unwrap(),
                expires: end,
            },
        ];
        let (out, incoming) = tokio::join!(dial(a, candidates, end, rx), b.accept());
        let (a, path) = out.unwrap();
        let incoming = incoming.unwrap();
        assert_eq!(a.address().unwrap(), original);
        path.send(bytes::Bytes::from_static(b"same socket"))
            .unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), incoming.receive())
                .await
                .unwrap()
                .unwrap(),
            bytes::Bytes::from_static(b"same socket")
        );
    }

    #[tokio::test]
    async fn cancellation_and_authority_channel_loss_release_socket() {
        for drop_sender in [false, true] {
            let (a, _b) = pair();
            let address = a.address().unwrap();
            let (cancel, rx) = watch::channel(false);
            if drop_sender {
                drop(cancel);
            } else {
                cancel.send(true).unwrap();
            }
            let end = Instant::now() + Duration::from_secs(10);
            let result = dial(
                a,
                vec![Candidate {
                    address: "127.0.0.1:1".parse().unwrap(),
                    expires: end,
                }],
                end,
                rx,
            )
            .await;
            assert!(matches!(result, Err(Error::Closed)));
            // Quinn releases its socket asynchronously after endpoint drop.
            tokio::time::timeout(Duration::from_secs(2), async {
                loop {
                    if std::net::UdpSocket::bind(address).is_ok() {
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
        }
    }

    #[tokio::test]
    async fn invalid_budgets_duplicates_and_expiry_fail_closed() {
        for count in [0, 2, 9] {
            let (a, b) = pair();
            let (_cancel, rx) = watch::channel(false);
            let end = Instant::now() + Duration::from_secs(10);
            let candidates = (0..count)
                .map(|_| Candidate {
                    address: b.address().unwrap(),
                    expires: end,
                })
                .collect();
            assert!(matches!(
                dial(a, candidates, end, rx).await,
                Err(Error::Configuration)
            ));
        }
        let (a, b) = pair();
        let (_cancel, rx) = watch::channel(false);
        let now = Instant::now();
        assert!(matches!(
            dial(
                a,
                vec![Candidate {
                    address: b.address().unwrap(),
                    expires: now
                }],
                now + Duration::from_secs(1),
                rx
            )
            .await,
            Err(Error::Timeout)
        ));
    }

    #[tokio::test]
    async fn failed_candidate_advances_to_authenticated_peer() {
        let (a, b) = pair();
        let wrong_key = SessionKey::generate().unwrap();
        let wrong = Peer::bind(
            "127.0.0.1:0".parse().unwrap(),
            wrong_key,
            SessionKey::generate().unwrap().certificate(),
        )
        .unwrap();
        let (_cancel, rx) = watch::channel(false);
        let end = Instant::now() + Duration::from_secs(10);
        let candidates = vec![
            Candidate {
                address: wrong.address().unwrap(),
                expires: end,
            },
            Candidate {
                address: b.address().unwrap(),
                expires: end,
            },
        ];
        let (out, bad, good) =
            tokio::join!(dial(a, candidates, end, rx), wrong.accept(), b.accept());
        assert!(bad.is_err());
        assert!(out.is_ok());
        assert!(good.is_ok());
    }

    #[tokio::test]
    async fn in_flight_cancel_and_candidate_deadline_bound_handshakes() {
        for cancel_in_flight in [false, true] {
            let (a, _b) = pair();
            // Retain a silent UDP socket so no ICMP refusal shortens this test.
            let silent = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
            let (cancel, rx) = watch::channel(false);
            let now = Instant::now();
            let candidate_end = now + Duration::from_millis(150);
            let operation = dial(
                a,
                vec![Candidate {
                    address: silent.local_addr().unwrap(),
                    expires: candidate_end,
                }],
                now + Duration::from_secs(10),
                rx,
            );
            let signal = async {
                tokio::time::sleep(Duration::from_millis(25)).await;
                if cancel_in_flight {
                    cancel.send(true).unwrap();
                }
                // Keep authority alive through the candidate's expiry case.
                tokio::time::sleep(Duration::from_millis(200)).await;
            };
            let (result, ()) = tokio::time::timeout(Duration::from_secs(2), async {
                tokio::join!(operation, signal)
            })
            .await
            .unwrap();
            if cancel_in_flight {
                assert!(matches!(result, Err(Error::Closed)));
            } else {
                assert!(matches!(result, Err(Error::Timeout)));
            }
        }
    }
}
