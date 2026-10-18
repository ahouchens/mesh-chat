//! Admitted-only recovery: TLS key possession, then service-owned RNS authority.
//! No packet can cross this channel before both protected services approve.
use crate::{BoundSocket, Error, SessionKey, MAX_PACKET};
use bytes::Bytes;
use quinn::crypto::rustls::{QuicClientConfig, QuicServerConfig};
use rustls::{
    client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier},
    pki_types::{CertificateDer, ServerName, UnixTime},
    server::danger::{ClientCertVerified, ClientCertVerifier},
    DigitallySignedStruct, SignatureScheme,
};
use std::{
    net::SocketAddr,
    sync::{
        atomic::{AtomicBool, AtomicU8, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    sync::{mpsc, watch},
    time::Instant,
};

const CAPSULE: usize = 20 * 1024;
const ALPN: &[u8] = b"mesh-direct-recovery/1";

/// Deliberately establishes key possession only. Membership is NOT established
/// by this verifier. Standard rustls signature verification parses the leaf and
/// verifies CertificateVerify; the RNS service must then bind that exact leaf.
#[derive(Debug)]
struct Possession;
fn leaf(cert: &CertificateDer<'_>, chain: &[CertificateDer<'_>]) -> Result<(), rustls::Error> {
    if cert.is_empty() || cert.len() > 4096 || !chain.is_empty() {
        return Err(rustls::Error::General(
            "invalid recovery certificate".into(),
        ));
    }
    Ok(())
}
fn signature(
    message: &[u8],
    cert: &CertificateDer<'_>,
    dss: &DigitallySignedStruct,
) -> Result<HandshakeSignatureValid, rustls::Error> {
    rustls::crypto::verify_tls13_signature(
        message,
        cert,
        dss,
        &rustls::crypto::ring::default_provider().signature_verification_algorithms,
    )
}
impl ServerCertVerifier for Possession {
    fn verify_server_cert(
        &self,
        cert: &CertificateDer<'_>,
        chain: &[CertificateDer<'_>],
        _: &ServerName<'_>,
        _: &[u8],
        _: UnixTime,
    ) -> Result<ServerCertVerified, rustls::Error> {
        leaf(cert, chain)?;
        Ok(ServerCertVerified::assertion())
    }
    fn verify_tls12_signature(
        &self,
        _: &[u8],
        _: &CertificateDer<'_>,
        _: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        Err(rustls::Error::General("TLS 1.3 required".into()))
    }
    fn verify_tls13_signature(
        &self,
        m: &[u8],
        c: &CertificateDer<'_>,
        d: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        signature(m, c, d)
    }
    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        rustls::crypto::ring::default_provider()
            .signature_verification_algorithms
            .supported_schemes()
    }
}
impl ClientCertVerifier for Possession {
    fn root_hint_subjects(&self) -> &[rustls::DistinguishedName] {
        &[]
    }
    fn verify_client_cert(
        &self,
        c: &CertificateDer<'_>,
        chain: &[CertificateDer<'_>],
        _: UnixTime,
    ) -> Result<ClientCertVerified, rustls::Error> {
        leaf(c, chain)?;
        Ok(ClientCertVerified::assertion())
    }
    fn verify_tls12_signature(
        &self,
        _: &[u8],
        _: &CertificateDer<'_>,
        _: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        Err(rustls::Error::General("TLS 1.3 required".into()))
    }
    fn verify_tls13_signature(
        &self,
        m: &[u8],
        c: &CertificateDer<'_>,
        d: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        signature(m, c, d)
    }
    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        rustls::crypto::ring::default_provider()
            .signature_verification_algorithms
            .supported_schemes()
    }
}

pub struct Evidence {
    pub certificate: Vec<u8>,
    pub capsule: Vec<u8>,
    pub token: [u8; 32],
}
pub struct Running {
    pub state: Arc<AtomicU8>,
    pub evidence: Arc<Mutex<Option<Evidence>>>,
    approve: watch::Sender<Option<[u8; 32]>>,
    cancel: watch::Sender<bool>,
    outgoing: mpsc::Sender<Bytes>,
    incoming: mpsc::Receiver<Bytes>,
    endpoint: quinn::Endpoint,
    pub certificate: Vec<u8>,
    client: Arc<AtomicBool>,
}
impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.cancel.send(true);
        self.endpoint.close(0u32.into(), b"retired");
    }
}

fn endpoint(bound: BoundSocket, key: SessionKey) -> Result<quinn::Endpoint, Error> {
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let mut server = rustls::ServerConfig::builder_with_provider(provider.clone())
        .with_protocol_versions(&[&rustls::version::TLS13])
        .map_err(|_| Error::Configuration)?
        .with_client_cert_verifier(Arc::new(Possession))
        .with_single_cert(vec![key.cert.clone()], key.key.clone_key().into())
        .map_err(|_| Error::Configuration)?;
    server.alpn_protocols = vec![ALPN.to_vec()];
    server.send_tls13_tickets = 0;
    server.max_early_data_size = 0;
    let mut client = rustls::ClientConfig::builder_with_provider(provider)
        .with_protocol_versions(&[&rustls::version::TLS13])
        .map_err(|_| Error::Configuration)?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(Possession))
        .with_client_auth_cert(vec![key.cert], key.key.into())
        .map_err(|_| Error::Configuration)?;
    client.alpn_protocols = vec![ALPN.to_vec()];
    client.enable_early_data = false;
    client.resumption = rustls::client::Resumption::disabled();
    let mut transport = quinn::TransportConfig::default();
    transport.max_idle_timeout(Some(
        Duration::from_secs(15)
            .try_into()
            .map_err(|_| Error::Configuration)?,
    ));
    transport.keep_alive_interval(Some(Duration::from_secs(5)));
    transport.max_concurrent_bidi_streams(0u32.into());
    transport.max_concurrent_uni_streams(2u32.into());
    transport.stream_receive_window((CAPSULE as u32).into());
    transport.receive_window((2 * CAPSULE as u32).into());
    transport.datagram_receive_buffer_size(Some(32 * MAX_PACKET));
    transport.datagram_send_buffer_size(32 * MAX_PACKET);
    let transport = Arc::new(transport);
    let mut server = quinn::ServerConfig::with_crypto(Arc::new(
        QuicServerConfig::try_from(server).map_err(|_| Error::Configuration)?,
    ));
    server.transport_config(transport.clone());
    server.max_incoming(2);
    server.incoming_buffer_size(16 * 1024);
    server.incoming_buffer_size_total(32 * 1024);
    // Standard authenticated client migration / NAT rebinding only.
    server.migration(true);
    let mut client = quinn::ClientConfig::new(Arc::new(
        QuicClientConfig::try_from(client).map_err(|_| Error::Configuration)?,
    ));
    client.transport_config(transport);
    let mut endpoint = quinn::Endpoint::new(
        quinn::EndpointConfig::default(),
        Some(server),
        bound.socket,
        Arc::new(quinn::TokioRuntime),
    )
    .map_err(|_| Error::Socket)?;
    endpoint.set_default_client_config(client);
    Ok(endpoint)
}

async fn exchange(
    connection: &quinn::Connection,
    local: &[u8],
    maximum: usize,
) -> Result<Vec<u8>, Error> {
    let send = async {
        let mut stream = connection.open_uni().await.map_err(|_| Error::Closed)?;
        stream.write_all(local).await.map_err(|_| Error::Closed)?;
        stream.finish().map_err(|_| Error::Closed)
    };
    let receive = async {
        let mut stream = connection.accept_uni().await.map_err(|_| Error::Closed)?;
        stream
            .read_to_end(maximum)
            .await
            .map_err(|_| Error::Configuration)
    };
    let (_, remote) = tokio::try_join!(send, receive)?;
    Ok(remote)
}

impl Running {
    pub fn start(
        bound: BoundSocket,
        key: SessionKey,
        capsule: Vec<u8>,
        candidates: Vec<SocketAddr>,
        client: bool,
        attempt: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        if capsule.is_empty()
            || capsule.len() > CAPSULE
            || candidates.len() > 8
            || (client && candidates.is_empty())
            || attempt.is_zero()
            || attempt > Duration::from_secs(60)
            || lifetime < attempt
            || lifetime > Duration::from_secs(3600)
            || candidates
                .iter()
                .any(|a| a.port() == 0 || a.ip().is_unspecified() || a.ip().is_multicast())
        {
            return Err(Error::Configuration);
        }
        let certificate = key.certificate().to_vec();
        let endpoint = endpoint(bound, key)?;
        let worker_endpoint = endpoint.clone();
        let state = Arc::new(AtomicU8::new(0));
        let status = state.clone();
        let evidence = Arc::new(Mutex::new(None));
        let pending = evidence.clone();
        let (approve, mut approved) = watch::channel(None);
        let (cancel, mut cancelled) = watch::channel(false);
        let (outgoing, mut outgoing_rx) = mpsc::channel::<Bytes>(32);
        let (incoming_tx, incoming) = mpsc::channel(32);
        let actual_client = Arc::new(AtomicBool::new(false));
        let worker_client = actual_client.clone();
        tokio::spawn(async move {
            let work = async {
                let deadline = Instant::now() + attempt;
                let connecting = async {
                    for index in 0..64 {
                        // Alternate standard connect/listen windows so a
                        // changed server address can recover through a known
                        // reachable client address. The preferred role orders
                        // the first attempt; it is not discovery authority.
                        let dial = client == (index % 2 == 0);
                        // Both peers may dial from the retained endpoint during
                        // alternating rounds. Every selected connection still
                        // crosses the capsule and service approval gate.
                        let target = candidates
                            .get((index / 2) % candidates.len().max(1))
                            .copied();
                        let outgoing = async {
                            let address = target.ok_or(Error::Timeout)?;
                            crate::traversal::pace(deadline).await?;
                            let pending = worker_endpoint
                                .connect(address, "mesh-direct.invalid")
                                .map_err(|_| Error::Handshake)?;
                            pending.await.map_err(|_| Error::Handshake)
                        };
                        let incoming = async {
                            let pending = worker_endpoint.accept().await.ok_or(Error::Closed)?;
                            pending.await.map_err(|_| Error::Handshake)
                        };
                        let is_client = dial && target.is_some();
                        // Recovery alternates roles. A listening round must not
                        // create an auxiliary connection: an unhosted peer has
                        // no candidate and always listens, so it could select
                        // that auxiliary handshake just before we close it.
                        // Outbound checks occur in the next dial round instead.
                        let selected = async {
                            if is_client {
                                outgoing.await
                            } else {
                                incoming.await
                            }
                        };
                        let connected = tokio::time::timeout(Duration::from_millis(1500), selected)
                            .await
                            .ok()
                            .and_then(Result::ok);
                        if let Some(connection) = connected {
                            // A completed TLS handshake may belong to a peer
                            // that already retired this attempt. Do not let its
                            // closed channel consume the entire recovery window.
                            // No service evidence or application data is exposed
                            // until the encrypted capsule exchange completes.
                            let remote = tokio::time::timeout_at(
                                deadline.min(Instant::now() + Duration::from_secs(10)),
                                exchange(&connection, &capsule, CAPSULE),
                            )
                            .await;
                            if let Ok(Ok(remote)) = remote {
                                worker_client
                                    .store(dial && !candidates.is_empty(), Ordering::Release);
                                return Ok((connection, remote));
                            }
                            connection.close(0u32.into(), b"incomplete recovery");
                        }
                        tokio::time::sleep(Duration::from_millis(500)).await;
                    }
                    Err(Error::Timeout)
                };
                let (connection, remote) = tokio::time::timeout_at(deadline, connecting)
                    .await
                    .map_err(|_| Error::Timeout)??;
                if connection.max_datagram_size().unwrap_or(0) < MAX_PACKET {
                    return Err::<(), Error>(Error::DatagramSize);
                }
                let auth = async {
                    let certs = connection
                        .peer_identity()
                        .ok_or(Error::Identity)?
                        .downcast::<Vec<CertificateDer<'static>>>()
                        .map_err(|_| Error::Identity)?;
                    if certs.len() != 1 || certs[0].len() > 4096 {
                        return Err(Error::Identity);
                    }
                    let mut token = [0; 32];
                    connection
                        .export_keying_material(
                            &mut token,
                            b"mesh-direct-service-authorization",
                            b"",
                        )
                        .map_err(|_| Error::Identity)?;
                    *pending.lock().map_err(|_| Error::Closed)? = Some(Evidence {
                        certificate: certs[0].to_vec(),
                        capsule: remote,
                        token,
                    });
                    status.store(3, Ordering::Release);
                    approved
                        .wait_for(|v| *v == Some(token))
                        .await
                        .map_err(|_| Error::Closed)?;
                    if exchange(&connection, b"approved", 8).await? != b"approved" {
                        return Err(Error::Identity);
                    }
                    *pending.lock().map_err(|_| Error::Closed)? = None;
                    Ok::<(), Error>(())
                };
                tokio::time::timeout(Duration::from_secs(10), auth)
                    .await
                    .map_err(|_| Error::Timeout)??;
                status.store(1, Ordering::Release);
                loop {
                    tokio::select! {
                        packet = outgoing_rx.recv() => match packet {
                            Some(p) => { connection.send_datagram(p).map_err(|_| Error::Closed)?; },
                            None => return Err(Error::Closed),
                        },
                        packet = connection.read_datagram() => {
                            let p = packet.map_err(|_| Error::Closed)?;
                            if p.is_empty() || p.len()>MAX_PACKET { return Err::<(), Error>(Error::DatagramSize); }
                            match incoming_tx.try_send(p) {
                                Ok(()) | Err(mpsc::error::TrySendError::Full(_)) => {},
                                Err(_) => return Err(Error::Closed),
                            }
                        }
                    }
                }
            };
            tokio::select! { biased;
                _ = cancelled.wait_for(|v| *v) => {},
                _ = tokio::time::sleep(lifetime) => {},
                _ = work => {},
            }
            status.store(2, Ordering::Release);
            worker_endpoint.close(0u32.into(), b"retired");
        });
        Ok(Self {
            state,
            evidence,
            approve,
            cancel,
            outgoing,
            incoming,
            endpoint,
            certificate,
            client: actual_client,
        })
    }
    pub fn authorize(&self, token: [u8; 32]) -> Result<(), Error> {
        if self.state.load(Ordering::Acquire) != 3
            || self
                .evidence
                .lock()
                .map_err(|_| Error::Closed)?
                .as_ref()
                .is_none_or(|e| e.token != token)
        {
            return Err(Error::Identity);
        }
        self.approve.send(Some(token)).map_err(|_| Error::Closed)
    }
    pub fn send(&self, packets: Vec<Bytes>) -> Result<(), Error> {
        if self.state.load(Ordering::Acquire) != 1 {
            return Err(Error::Identity);
        }
        if packets.len() > 32 || packets.iter().any(|p| p.is_empty() || p.len() > MAX_PACKET) {
            return Err::<(), Error>(Error::DatagramSize);
        }
        let permits = self
            .outgoing
            .try_reserve_many(packets.len())
            .map_err(|_| Error::QueueFull)?;
        for (permit, packet) in permits.zip(packets) {
            permit.send(packet);
        }
        Ok(())
    }
    pub fn poll(&mut self) -> (u8, Vec<Bytes>) {
        let state = self.state.load(Ordering::Acquire);
        let mut packets = vec![];
        if state == 1 {
            while packets.len() < 32 {
                if let Ok(p) = self.incoming.try_recv() {
                    packets.push(p);
                } else {
                    break;
                }
            }
        }
        (state, packets)
    }
    pub fn address(&self) -> Result<SocketAddr, Error> {
        self.endpoint.local_addr().map_err(|_| Error::Socket)
    }
    pub fn migrate(&self, bound: BoundSocket) -> Result<(), Error> {
        if !self.client.load(Ordering::Acquire) || self.state.load(Ordering::Acquire) != 1 {
            return Err(Error::Configuration);
        }
        self.endpoint
            .rebind(bound.socket)
            .map_err(|_| Error::Socket)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    async fn state(peer: &Running, expected: u8) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while peer.state.load(Ordering::Acquire) != expected {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
    }
    #[tokio::test]
    async fn service_gates_fresh_certificates_packets_and_client_migration() {
        let a = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let b = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let target = b.address().unwrap();
        let old = SessionKey::generate().unwrap().certificate();
        let mut server = Running::start(
            b,
            SessionKey::generate().unwrap(),
            b"encrypted server binding".to_vec(),
            vec![],
            false,
            Duration::from_secs(10),
            Duration::from_secs(30),
        )
        .unwrap();
        let mut client = Running::start(
            a,
            SessionKey::generate().unwrap(),
            b"encrypted client binding".to_vec(),
            vec![target],
            true,
            Duration::from_secs(10),
            Duration::from_secs(30),
        )
        .unwrap();
        assert_ne!(client.certificate, old.as_ref());
        assert_eq!(
            client.send(vec![Bytes::from_static(b"early")]),
            Err(Error::Identity)
        );
        state(&client, 3).await;
        state(&server, 3).await;
        assert_eq!(
            client
                .evidence
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .certificate,
            server.certificate
        );
        assert_eq!(
            server.evidence.lock().unwrap().as_ref().unwrap().capsule,
            b"encrypted client binding"
        );
        assert_eq!(client.authorize([0; 32]), Err(Error::Identity));
        let token = client.evidence.lock().unwrap().as_ref().unwrap().token;
        client.authorize(token).unwrap();
        tokio::time::sleep(Duration::from_millis(30)).await;
        assert_eq!(client.state.load(Ordering::Acquire), 3);
        let token = server.evidence.lock().unwrap().as_ref().unwrap().token;
        server.authorize(token).unwrap();
        state(&client, 1).await;
        state(&server, 1).await;
        assert!(server
            .migrate(BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap())
            .is_err());
        let before = client.address().unwrap();
        client
            .migrate(BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap())
            .unwrap();
        assert_ne!(before, client.address().unwrap());
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                client
                    .send(vec![Bytes::from_static(b"after migration")])
                    .unwrap();
                tokio::time::sleep(Duration::from_millis(50)).await;
                if !server.poll().1.is_empty() {
                    break;
                }
            }
            loop {
                server.send(vec![Bytes::from_static(b"receipt")]).unwrap();
                tokio::time::sleep(Duration::from_millis(50)).await;
                if !client.poll().1.is_empty() {
                    break;
                }
            }
        })
        .await
        .unwrap();
        drop(server);
        state(&client, 2).await;
        assert!(client.send(vec![Bytes::from_static(b"retired")]).is_err());
    }
    #[tokio::test]
    async fn lost_server_address_uses_known_peer_address_with_fresh_authority() {
        let a = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let known_client = a.address().unwrap();
        let b = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let wrong = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server = Running::start(
            b,
            SessionKey::generate().unwrap(),
            vec![1],
            vec![known_client],
            false,
            Duration::from_secs(20),
            Duration::from_secs(30),
        )
        .unwrap();
        let client = Running::start(
            a,
            SessionKey::generate().unwrap(),
            vec![2],
            vec![wrong.address().unwrap()],
            true,
            Duration::from_secs(20),
            Duration::from_secs(30),
        )
        .unwrap();
        tokio::time::timeout(Duration::from_secs(18), async {
            while client.state.load(Ordering::Acquire) != 3
                || server.state.load(Ordering::Acquire) != 3
            {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        assert!(!client.client.load(Ordering::Acquire));
        assert!(server.client.load(Ordering::Acquire));
        // Merely reaching a changed peer still cannot forward RNS packets.
        assert_eq!(
            server.send(vec![Bytes::from_static(b"unapproved")]),
            Err(Error::Identity)
        );
        for peer in [&client, &server] {
            let token = peer.evidence.lock().unwrap().as_ref().unwrap().token;
            peer.authorize(token).unwrap();
        }
        state(&client, 1).await;
        state(&server, 1).await;
    }
    #[tokio::test]
    async fn unhosted_restart_survives_listener_starting_during_a_listen_round() {
        let bound = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let target = bound.address().unwrap();
        let client = Running::start(
            BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap(),
            SessionKey::generate().unwrap(),
            vec![1],
            vec![target],
            true,
            Duration::from_secs(15),
            Duration::from_secs(30),
        )
        .unwrap();
        // The first outgoing check times out. The owner starts while this
        // restarted unhosted device is in its next (listening) round.
        tokio::time::sleep(Duration::from_millis(2100)).await;
        let server = Running::start(
            bound,
            SessionKey::generate().unwrap(),
            vec![2],
            vec![],
            false,
            Duration::from_secs(15),
            Duration::from_secs(30),
        )
        .unwrap();
        tokio::time::timeout(Duration::from_secs(10), async {
            while client.state.load(Ordering::Acquire) != 3
                || server.state.load(Ordering::Acquire) != 3
            {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        for peer in [&client, &server] {
            let token = peer.evidence.lock().unwrap().as_ref().unwrap().token;
            peer.authorize(token).unwrap();
        }
        state(&client, 1).await;
        state(&server, 1).await;
    }

    #[tokio::test]
    async fn closed_pre_authorization_connection_does_not_consume_recovery_window() {
        let bound = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let target = bound.address().unwrap();
        let mut server = Running::start(
            bound,
            SessionKey::generate().unwrap(),
            vec![1],
            vec![],
            false,
            Duration::from_secs(15),
            Duration::from_secs(30),
        )
        .unwrap();
        let stale = endpoint(
            BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap(),
            SessionKey::generate().unwrap(),
        )
        .unwrap();
        let retired = stale
            .connect(target, "mesh-direct.invalid")
            .unwrap()
            .await
            .unwrap();
        // Reproduce an old native attempt closing immediately after TLS, before
        // either service has received or approved the recovery capsule.
        retired.close(0u32.into(), b"retired attempt");
        tokio::time::sleep(Duration::from_millis(250)).await;
        assert_eq!(server.state.load(Ordering::Acquire), 0);
        assert!(server.evidence.lock().unwrap().is_none());
        let client = Running::start(
            BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap(),
            SessionKey::generate().unwrap(),
            vec![2],
            vec![target],
            true,
            Duration::from_secs(15),
            Duration::from_secs(30),
        )
        .unwrap();
        state(&client, 3).await;
        state(&server, 3).await;
        assert_eq!(
            server.send(vec![Bytes::from_static(b"early")]),
            Err(Error::Identity)
        );
        assert_eq!(
            server
                .evidence
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .certificate,
            client.certificate
        );
        for peer in [&client, &server] {
            let token = peer.evidence.lock().unwrap().as_ref().unwrap().token;
            peer.authorize(token).unwrap();
        }
        state(&client, 1).await;
        state(&server, 1).await;
        client.send(vec![Bytes::from_static(b"approved")]).unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                if !server.poll().1.is_empty() {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
    }

    #[tokio::test]
    async fn unauthenticated_channels_expire_without_packets() {
        let mut peer = Running::start(
            BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap(),
            SessionKey::generate().unwrap(),
            vec![1],
            vec![],
            false,
            Duration::from_millis(40),
            Duration::from_millis(50),
        )
        .unwrap();
        state(&peer, 2).await;
        assert!(peer.poll().1.is_empty());
        assert!(peer.authorize([0; 32]).is_err());
    }
}
