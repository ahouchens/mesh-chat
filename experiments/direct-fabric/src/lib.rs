//! Native authenticated direct transport and controlled-peer qualification.
//!
//! The protected service supplies certificate authorization. The app embeds the
//! bounded host through private IPC; enabling an RNS interface still requires
//! service-owned identity, scope, bootstrap isolation and lifecycle checks.

use bytes::Bytes;
pub mod attempt;
pub mod host;
pub mod paths;
pub mod recovery;
pub mod traversal;
use quinn::crypto::rustls::{QuicClientConfig, QuicServerConfig};
use rustls::pki_types::{CertificateDer, PrivatePkcs8KeyDer};
use std::{
    collections::VecDeque,
    net::{SocketAddr, UdpSocket},
    sync::{Arc, Mutex},
    time::Duration,
};

pub const ALPN: &[u8] = b"mesh-direct-proof/1";
// Pinned RNS 1.5.5 base MTU (500), plus 128-bit IFAC (16). QUIC adds
// framing outside this payload. This proof does not enable a larger RNS MTU.
pub const MAX_PACKET: usize = 516;
pub const QUEUE_BYTES: usize = 64 * 1024;
pub const QUEUE_ITEMS: usize = 128;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);
const IDLE_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    Configuration,
    Socket,
    Handshake,
    Timeout,
    Identity,
    DatagramSize,
    Closed,
    QueueFull,
}

pub struct SessionKey {
    cert: CertificateDer<'static>,
    key: PrivatePkcs8KeyDer<'static>,
}

impl SessionKey {
    pub(crate) fn duplicate(&self) -> Self {
        Self {
            cert: self.cert.clone(),
            key: self.key.clone_key(),
        }
    }
    pub fn generate() -> Result<Self, Error> {
        let key = rcgen::generate_simple_self_signed(vec!["mesh-direct.invalid".into()])
            .map_err(|_| Error::Configuration)?;
        Ok(Self {
            cert: key.cert.der().clone(),
            key: PrivatePkcs8KeyDer::from(key.key_pair.serialize_der()),
        })
    }

    /// Public certificate only; private key material has no export API.
    pub fn certificate(&self) -> CertificateDer<'static> {
        self.cert.clone()
    }
}

/// A byte AND item bounded application queue. A stalled peer cannot enqueue
/// unlimited tiny frames or an unlimited number of MTU-sized frames.
#[derive(Default)]
pub struct PacketQueue {
    items: VecDeque<Bytes>,
    bytes: usize,
}

impl PacketQueue {
    pub fn push(&mut self, packet: Bytes) -> Result<(), Error> {
        check_size(packet.len())?;
        if self.items.len() == QUEUE_ITEMS || self.bytes + packet.len() > QUEUE_BYTES {
            return Err(Error::QueueFull);
        }
        self.bytes += packet.len();
        self.items.push_back(packet);
        Ok(())
    }
    pub fn pop(&mut self) -> Option<Bytes> {
        let packet = self.items.pop_front()?;
        self.bytes -= packet.len();
        Some(packet)
    }
}

fn check_size(size: usize) -> Result<(), Error> {
    if size == 0 || size > MAX_PACKET {
        Err(Error::DatagramSize)
    } else {
        Ok(())
    }
}

/// Keeps the candidate's actual UDP socket alive while the service authorizes
/// its mapping and peer. No read/clone/export API permits a competing receiver.
pub struct BoundSocket {
    socket: UdpSocket,
}

impl BoundSocket {
    pub fn bind(address: SocketAddr) -> Result<Self, Error> {
        let socket = UdpSocket::bind(address).map_err(|_| Error::Socket)?;
        socket.set_nonblocking(true).map_err(|_| Error::Socket)?;
        Ok(Self { socket })
    }

    pub fn address(&self) -> Result<SocketAddr, Error> {
        self.socket.local_addr().map_err(|_| Error::Socket)
    }
}

/// Owns exactly one UDP socket for discovery/advertising and QUIC. Only Quinn
/// receives from this socket; there is no parallel probe receiver.
pub struct Peer {
    endpoint: quinn::Endpoint,
    expected: CertificateDer<'static>,
}

impl Peer {
    pub fn bind(
        address: SocketAddr,
        key: SessionKey,
        expected: CertificateDer<'static>,
    ) -> Result<Self, Error> {
        Self::from_bound_socket(BoundSocket::bind(address)?, key, expected)
    }

    /// Consume the still-owned candidate socket; never close and rebind it.
    pub fn from_bound_socket(
        bound: BoundSocket,
        key: SessionKey,
        expected: CertificateDer<'static>,
    ) -> Result<Self, Error> {
        let mut roots = rustls::RootCertStore::empty();
        roots
            .add(expected.clone())
            .map_err(|_| Error::Configuration)?;
        let roots = Arc::new(roots);
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let verifier = rustls::server::WebPkiClientVerifier::builder_with_provider(
            roots.clone(),
            provider.clone(),
        )
        .build()
        .map_err(|_| Error::Configuration)?;
        let mut server_tls = rustls::ServerConfig::builder_with_provider(provider.clone())
            .with_protocol_versions(&[&rustls::version::TLS13])
            .map_err(|_| Error::Configuration)?
            .with_client_cert_verifier(verifier)
            .with_single_cert(vec![key.cert.clone()], key.key.clone_key().into())
            .map_err(|_| Error::Configuration)?;
        server_tls.alpn_protocols = vec![ALPN.to_vec()];
        server_tls.max_early_data_size = 0;
        server_tls.send_tls13_tickets = 0;

        let mut client_tls = rustls::ClientConfig::builder_with_provider(provider)
            .with_protocol_versions(&[&rustls::version::TLS13])
            .map_err(|_| Error::Configuration)?
            .with_root_certificates(roots)
            .with_client_auth_cert(vec![key.cert], key.key.into())
            .map_err(|_| Error::Configuration)?;
        client_tls.alpn_protocols = vec![ALPN.to_vec()];
        client_tls.enable_early_data = false;
        client_tls.resumption = rustls::client::Resumption::disabled();

        let mut transport = quinn::TransportConfig::default();
        transport.max_idle_timeout(Some(
            IDLE_TIMEOUT.try_into().map_err(|_| Error::Configuration)?,
        ));
        transport.keep_alive_interval(Some(Duration::from_secs(5)));
        transport.max_concurrent_bidi_streams(0u32.into());
        transport.max_concurrent_uni_streams(0u32.into());
        transport.datagram_receive_buffer_size(Some(QUEUE_BYTES));
        transport.datagram_send_buffer_size(QUEUE_BYTES);
        let transport = Arc::new(transport);
        let mut server = quinn::ServerConfig::with_crypto(Arc::new(
            QuicServerConfig::try_from(server_tls).map_err(|_| Error::Configuration)?,
        ));
        server.transport_config(transport.clone());
        server.max_incoming(2);
        server.incoming_buffer_size(16 * 1024);
        server.incoming_buffer_size_total(32 * 1024);
        // Migration is a separate proof. Do not accept peer addresses outside
        // the controlled topology or pretend this implements server migration.
        server.migration(false);
        let mut client = quinn::ClientConfig::new(Arc::new(
            QuicClientConfig::try_from(client_tls).map_err(|_| Error::Configuration)?,
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
        Ok(Self { endpoint, expected })
    }

    pub fn address(&self) -> Result<SocketAddr, Error> {
        self.endpoint.local_addr().map_err(|_| Error::Socket)
    }

    pub async fn connect(&self, address: SocketAddr) -> Result<Path, Error> {
        let connecting = self
            .endpoint
            .connect(address, "mesh-direct.invalid")
            .map_err(|_| Error::Handshake)?;
        let connection = tokio::time::timeout(HANDSHAKE_TIMEOUT, connecting)
            .await
            .map_err(|_| Error::Timeout)?
            .map_err(|_| Error::Handshake)?;
        self.authenticate(connection)
    }

    pub async fn accept(&self) -> Result<Path, Error> {
        let connection = tokio::time::timeout(HANDSHAKE_TIMEOUT, async {
            let incoming = self.endpoint.accept().await.ok_or(Error::Closed)?;
            incoming.await.map_err(|_| Error::Handshake)
        })
        .await
        .map_err(|_| Error::Timeout)??;
        self.authenticate(connection)
    }

    fn authenticate(&self, connection: quinn::Connection) -> Result<Path, Error> {
        let valid = connection
            .peer_identity()
            .and_then(|value| value.downcast::<Vec<CertificateDer<'static>>>().ok())
            .is_some_and(|chain| chain.len() == 1 && chain[0] == self.expected);
        if !valid {
            connection.close(1u32.into(), b"identity");
            return Err(Error::Identity);
        }
        if connection.max_datagram_size().unwrap_or(0) < MAX_PACKET {
            connection.close(2u32.into(), b"datagram_size");
            return Err(Error::DatagramSize);
        }
        let submitted = connection.stats().frame_tx.datagram;
        Ok(Path {
            connection,
            submitted: Mutex::new(submitted),
        })
    }

    pub fn close(&self) {
        self.endpoint.close(0u32.into(), b"closed");
    }
}

impl Drop for Peer {
    fn drop(&mut self) {
        self.close();
    }
}

pub struct Path {
    connection: quinn::Connection,
    submitted: Mutex<u64>,
}

impl Path {
    pub fn close(&self) {
        self.connection.close(0u32.into(), b"check_complete");
    }
    pub fn is_open(&self) -> bool {
        self.connection.close_reason().is_none()
    }
    pub fn send(&self, packet: Bytes) -> Result<(), Error> {
        check_size(packet.len())?;
        // Serialize admissions so concurrent senders cannot race either bound.
        // Quinn's DATAGRAM transmit counter releases item credits when a frame
        // leaves its queue; no delivery acknowledgment or retransmission is added.
        let mut submitted = self.submitted.lock().map_err(|_| Error::Closed)?;
        if !self.is_open() {
            return Err(Error::Closed);
        }
        if self.connection.max_datagram_size().unwrap_or(0) < MAX_PACKET {
            return Err(Error::DatagramSize);
        }
        if submitted.saturating_sub(self.connection.stats().frame_tx.datagram) >= QUEUE_ITEMS as u64
            || self.connection.datagram_send_buffer_space() < packet.len()
        {
            return Err(Error::QueueFull);
        }
        self.connection
            .send_datagram(packet)
            .map_err(|_| Error::Closed)?;
        *submitted = submitted.saturating_add(1);
        Ok(())
    }
    pub async fn receive(&self) -> Result<Bytes, Error> {
        let packet = self
            .connection
            .read_datagram()
            .await
            .map_err(|_| Error::Closed)?;
        if check_size(packet.len()).is_err() {
            self.connection.close(2u32.into(), b"datagram_size");
            return Err(Error::DatagramSize);
        }
        Ok(packet)
    }
    pub async fn closed(&self) {
        let _ = self.connection.closed().await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pair() -> (Peer, Peer) {
        let a_socket = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let b_socket = BoundSocket::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let a_candidate = a_socket.address().unwrap();
        let b_candidate = b_socket.address().unwrap();
        let a = SessionKey::generate().unwrap();
        let b = SessionKey::generate().unwrap();
        let ac = a.certificate();
        let bc = b.certificate();
        let a = Peer::from_bound_socket(a_socket, a, bc).unwrap();
        let b = Peer::from_bound_socket(b_socket, b, ac).unwrap();
        assert_eq!(a.address().unwrap(), a_candidate);
        assert_eq!(b.address().unwrap(), b_candidate);
        (a, b)
    }

    #[tokio::test]
    async fn packets_boundaries_same_socket_and_engine_death() {
        let (a, b) = pair();
        let before = a.address().unwrap();
        let (ap, bp) = tokio::join!(a.connect(b.address().unwrap()), b.accept());
        let (ap, bp) = (ap.unwrap(), bp.unwrap());
        assert_eq!(a.address().unwrap(), before);
        for size in [1, 64, 500, MAX_PACKET] {
            let packet = Bytes::from(vec![size as u8; size]);
            ap.send(packet.clone()).unwrap();
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(2), bp.receive())
                    .await
                    .unwrap()
                    .unwrap(),
                packet
            );
            bp.send(packet.clone()).unwrap();
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(2), ap.receive())
                    .await
                    .unwrap()
                    .unwrap(),
                packet
            );
        }
        assert_eq!(
            ap.send(Bytes::from(vec![0; MAX_PACKET + 1])),
            Err(Error::DatagramSize)
        );
        drop(a);
        tokio::time::timeout(Duration::from_secs(2), bp.closed())
            .await
            .unwrap();
        assert!(!bp.is_open());
    }

    #[tokio::test]
    async fn native_send_queue_bounds_tiny_packets_and_reclaims_items() {
        let (a, b) = pair();
        let (ap, bp) = tokio::join!(a.connect(b.address().unwrap()), b.accept());
        let (ap, bp) = (ap.unwrap(), bp.unwrap());
        // The current-thread runtime cannot drain Quinn while this synchronous
        // loop runs, exposing item exhaustion well before the byte limit.
        for _ in 0..QUEUE_ITEMS {
            ap.send(Bytes::from_static(b"x")).unwrap();
        }
        assert_eq!(ap.send(Bytes::from_static(b"x")), Err(Error::QueueFull));
        for _ in 0..QUEUE_ITEMS {
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(5), bp.receive())
                    .await
                    .unwrap()
                    .unwrap(),
                Bytes::from_static(b"x")
            );
        }
        ap.send(Bytes::from_static(b"reclaimed")).unwrap();
    }

    #[tokio::test]
    async fn substituted_peer_key_cannot_authenticate() {
        let (a, b) = pair();
        let wrong = Peer::bind(
            "127.0.0.1:0".parse().unwrap(),
            SessionKey::generate().unwrap(),
            b.expected.clone(),
        )
        .unwrap();
        let (client, server) = tokio::join!(a.connect(wrong.address().unwrap()), wrong.accept());
        assert!(client.is_err());
        assert!(server.is_err());
    }

    #[tokio::test]
    async fn separate_local_process_cannot_inject_native_packets() {
        let (a, b) = pair();
        let inject = || {
            let python = std::env::var("MESH_DIRECT_BINDING_PYTHON")
                .expect("CI must configure Python for the local hostile-process test");
            let status = std::process::Command::new(python)
                .arg("-c")
                .arg(concat!(
                    "import socket,sys\n",
                    "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n",
                    "for port in map(int,sys.argv[1:]):\n",
                    " for packet in (b'forged RNS packet', b'\\xc0'+bytes(1199), bytes(8192)):\n",
                    "  for _ in range(8): s.sendto(packet,('127.0.0.1',port))\n",
                    "s.close()\n"
                ))
                .arg(a.address().unwrap().port().to_string())
                .arg(b.address().unwrap().port().to_string())
                .status()
                .expect("start unprivileged local injector");
            assert!(status.success());
        };
        // Knowing both ports grants no packet authority, before or after TLS.
        // The attacker has no inherited private control or packet pipe handles.
        inject();
        let (ap, bp) = tokio::join!(a.connect(b.address().unwrap()), b.accept());
        let (ap, bp) = (ap.unwrap(), bp.unwrap());
        inject();
        assert!(
            tokio::time::timeout(Duration::from_millis(250), ap.receive())
                .await
                .is_err()
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(250), bp.receive())
                .await
                .is_err()
        );
        for (sender, receiver) in [(&ap, &bp), (&bp, &ap)] {
            let packet = Bytes::from_static(b"authenticated after local injection");
            sender.send(packet.clone()).unwrap();
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(2), receiver.receive())
                    .await
                    .unwrap()
                    .unwrap(),
                packet
            );
        }
    }

    #[tokio::test]
    async fn authenticated_peer_sending_oversized_packet_closes_path() {
        let (a, b) = pair();
        let (ap, bp) = tokio::join!(a.connect(b.address().unwrap()), b.accept());
        let (ap, bp) = (ap.unwrap(), bp.unwrap());
        // Deliberately bypass the sender API to simulate a malicious peer.
        ap.connection
            .send_datagram(Bytes::from(vec![0; MAX_PACKET + 1]))
            .unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), bp.receive())
                .await
                .unwrap(),
            Err(Error::DatagramSize),
        );
        assert!(!bp.is_open());
    }

    #[test]
    fn queue_has_both_limits_and_releases_capacity() {
        let mut queue = PacketQueue::default();
        for _ in 0..QUEUE_ITEMS {
            queue.push(Bytes::from_static(b"a")).unwrap();
        }
        assert_eq!(queue.push(Bytes::from_static(b"a")), Err(Error::QueueFull));
        while queue.pop().is_some() {}
        for _ in 0..QUEUE_BYTES / MAX_PACKET {
            queue.push(Bytes::from(vec![0; MAX_PACKET])).unwrap();
        }
        assert_eq!(
            queue.push(Bytes::from(vec![0; MAX_PACKET])),
            Err(Error::QueueFull)
        );
        assert_eq!(queue.push(Bytes::new()), Err(Error::DatagramSize));
    }
}
