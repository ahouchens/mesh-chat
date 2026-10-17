//! Bounded dialing of service-authorized candidates on one native-owned socket.
//! No discovery, custom probes, retries after exhaustion, or TCP policy here.
use crate::{Error, Path, Peer};
use std::{collections::HashSet, net::SocketAddr, time::Duration};
use tokio::{sync::watch, time::Instant};

pub struct Candidate {
    pub address: SocketAddr,
    /// Converted once from verified document validity by the protected caller.
    pub expires: Instant,
}

/// Consumes the endpoint so cancellation, caller abandonment, and exhaustion
/// release the socket. Success returns that same owner with its authenticated
/// path. Only the deterministic QUIC client may invoke this operation.
pub async fn dial(
    peer: Peer,
    candidates: Vec<Candidate>,
    deadline: Instant,
    mut cancelled: watch::Receiver<bool>,
) -> Result<(Peer, Path), Error> {
    let now = Instant::now();
    if deadline <= now {
        return Err(Error::Timeout);
    }
    if deadline - now > Duration::from_secs(60) || candidates.is_empty() || candidates.len() > 8 {
        return Err(Error::Configuration);
    }
    let mut seen = HashSet::new();
    for candidate in &candidates {
        if candidate.address.port() == 0
            || candidate.address.ip().is_unspecified()
            || candidate.address.ip().is_multicast()
            || !seen.insert(candidate.address)
        {
            return Err(Error::Configuration);
        }
    }
    // Sequential handshakes cap native work at one outgoing attempt at a time.
    // Quinn alone receives and retransmits standard QUIC handshake packets.
    let attempts = async {
        for candidate in candidates {
            let until = deadline.min(candidate.expires);
            if Instant::now() >= until {
                continue;
            }
            if let Ok(Ok(path)) =
                tokio::time::timeout_at(until, peer.connect(candidate.address)).await
            {
                return Ok(path);
            }
        }
        Err(Error::Timeout)
    };
    let result = tokio::select! {
        biased;
        // A dropped service authority channel also cancels the endpoint.
        _ = cancelled.wait_for(|value| *value) => Err(Error::Closed),
        _ = tokio::time::sleep_until(deadline) => Err(Error::Timeout),
        result = attempts => result,
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
