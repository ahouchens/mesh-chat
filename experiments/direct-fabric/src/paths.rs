//! Several retained route sockets, one signed session and one selected path.
//! There is only one outgoing check at a time across all local/remote pairs.
use crate::{
    traversal::{self, Candidate, Statistics},
    Error, Path, Peer,
};
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};
use tokio::{sync::watch, task::JoinSet, time::Instant};

pub async fn connect(
    peers: Vec<Peer>,
    candidates: Vec<Candidate>,
    client: bool,
    deadline: Instant,
    mut cancelled: watch::Receiver<bool>,
    statistics: Arc<Statistics>,
) -> Result<(Arc<Peer>, Path), Error> {
    if peers.is_empty() || peers.len() > 4 || candidates.len() > 8 {
        return Err(Error::Configuration);
    }
    traversal::validate(&candidates, !client)?;
    let now = Instant::now();
    if deadline <= now || deadline - now > Duration::from_secs(60) {
        return Err(Error::Timeout);
    }
    let peers: Vec<_> = peers.into_iter().map(Arc::new).collect();
    let mut pairs = vec![];
    // Interleave interfaces for each remote candidate. No packet is sent using
    // an incompatible family or a newly rebound discovery socket.
    for (remote_index, remote) in candidates.iter().enumerate() {
        for (local_index, local) in peers.iter().enumerate() {
            if local.address()?.is_ipv4() == remote.address.is_ipv4() {
                pairs.push((local_index, remote_index));
            }
        }
    }
    let mut incoming = JoinSet::new();
    let incoming_budget = Arc::new(AtomicUsize::new(64));
    for (index, peer) in peers.iter().enumerate() {
        let peer = peer.clone();
        let statistics = statistics.clone();
        let incoming_budget = incoming_budget.clone();
        incoming.spawn(async move {
            while incoming_budget
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |left| {
                    left.checked_sub(1)
                })
                .is_ok()
            {
                if let Ok(path) = peer.accept().await {
                    statistics.authenticated.fetch_add(1, Ordering::Relaxed);
                    if !client {
                        return Ok((index, path));
                    }
                    path.close(); // Auxiliary server check; never application data.
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Err(Error::Timeout)
        });
    }
    let outgoing = async {
        let mut starts = 0;
        while starts < 64 && Instant::now() < deadline {
            let mut attempted = false;
            for &(local, remote) in &pairs {
                let until = deadline.min(candidates[remote].expires);
                if Instant::now() >= until {
                    continue;
                }
                attempted = true;
                traversal::pace(until).await?;
                let start = Instant::now();
                starts += 1;
                statistics.started.fetch_add(1, Ordering::Relaxed);
                if let Ok(Ok(path)) = tokio::time::timeout_at(
                    until.min(start + Duration::from_millis(1500)),
                    peers[local].connect(candidates[remote].address),
                )
                .await
                {
                    statistics.authenticated.fetch_add(1, Ordering::Relaxed);
                    if client {
                        return Ok((local, path));
                    }
                    path.close();
                }
                if starts == 64 {
                    break;
                }
                tokio::time::sleep_until(until.min(start + Duration::from_millis(500))).await;
            }
            if !attempted {
                break;
            }
        }
        if !client {
            std::future::pending::<()>().await;
        }
        Err(Error::Timeout)
    };
    let accepting = async {
        while let Some(result) = incoming.join_next().await {
            if let Ok(Ok(path)) = result {
                return Ok(path);
            }
        }
        Err(Error::Timeout)
    };
    let result = tokio::select! {
        biased;
        _ = cancelled.wait_for(|value| *value) => Err(Error::Closed),
        _ = tokio::time::sleep_until(deadline) => Err(Error::Timeout),
        result = outgoing => result,
        result = accepting => result,
    };
    incoming.abort_all();
    while incoming.join_next().await.is_some() {}
    match result {
        Ok((selected, path)) => {
            for (index, peer) in peers.iter().enumerate() {
                if index != selected {
                    peer.close();
                }
            }
            Ok((peers[selected].clone(), path))
        }
        Err(error) => Err(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SessionKey;

    #[tokio::test]
    async fn alternatives_keep_owned_sockets_and_select_one_bidirectional_path() {
        let akey = SessionKey::generate().unwrap();
        let bkey = SessionKey::generate().unwrap();
        let ac = akey.certificate();
        let bc = bkey.certificate();
        let a1 = Peer::bind("127.0.0.1:0".parse().unwrap(), akey.duplicate(), bc.clone()).unwrap();
        let a2 = Peer::bind("127.0.0.1:0".parse().unwrap(), akey, bc).unwrap();
        let aa = [a1.address().unwrap(), a2.address().unwrap()];
        let b = Peer::bind("127.0.0.1:0".parse().unwrap(), bkey, ac).unwrap();
        let ba = b.address().unwrap();
        let silent = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        let end = Instant::now() + Duration::from_secs(12);
        let (_tx, rx) = watch::channel(false);
        let stats = Arc::new(Statistics::default());
        let candidates = vec![
            Candidate {
                address: silent.local_addr().unwrap(),
                expires: end,
            },
            Candidate {
                address: ba,
                expires: end,
            },
        ];
        let (outgoing, incoming) = tokio::join!(
            connect(
                vec![a1, a2],
                candidates,
                true,
                end,
                rx.clone(),
                stats.clone()
            ),
            traversal::listen_with_checks(
                b,
                vec![
                    Candidate {
                        address: aa[0],
                        expires: end
                    },
                    Candidate {
                        address: aa[1],
                        expires: end
                    }
                ],
                end,
                rx
            )
        );
        let (a, apath) = outgoing.unwrap();
        let (_b, bpath) = incoming.unwrap();
        assert!(aa.contains(&a.address().unwrap()));
        assert!(stats.started.load(Ordering::Relaxed) >= 3);
        apath
            .send(bytes::Bytes::from_static(b"single-winner"))
            .unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), bpath.receive())
                .await
                .unwrap()
                .unwrap(),
            bytes::Bytes::from_static(b"single-winner")
        );
        bpath.send(bytes::Bytes::from_static(b"receipt")).unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), apath.receive())
                .await
                .unwrap()
                .unwrap(),
            bytes::Bytes::from_static(b"receipt")
        );
    }

    #[tokio::test]
    async fn cancellation_releases_every_owned_route() {
        let key = SessionKey::generate().unwrap();
        let expected = SessionKey::generate().unwrap().certificate();
        let peers = vec![
            Peer::bind(
                "127.0.0.1:0".parse().unwrap(),
                key.duplicate(),
                expected.clone(),
            )
            .unwrap(),
            Peer::bind("127.0.0.1:0".parse().unwrap(), key, expected).unwrap(),
        ];
        let addresses: Vec<_> = peers.iter().map(|p| p.address().unwrap()).collect();
        let (tx, rx) = watch::channel(false);
        tx.send(true).unwrap();
        let result = connect(
            peers,
            vec![],
            false,
            Instant::now() + Duration::from_secs(5),
            rx,
            Arc::new(Statistics::default()),
        )
        .await;
        assert!(matches!(result, Err(Error::Closed)));
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                if addresses
                    .iter()
                    .all(|address| std::net::UdpSocket::bind(address).is_ok())
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        })
        .await
        .unwrap();
    }
}
