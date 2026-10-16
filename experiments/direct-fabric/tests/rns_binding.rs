//! Cross-language proof: native keeps both private TLS keys; Python alone owns
//! the RNS identities and authorizes their public certificates. Not app IPC.
use bytes::Bytes;
use mesh_direct_proof::{Peer, SessionKey};
use std::{path::PathBuf, process::Command, time::Duration};

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[tokio::test]
async fn service_authorized_certificates_carry_native_datagrams() {
    let a = SessionKey::generate().unwrap();
    let b = SessionKey::generate().unwrap();
    let ac = a.certificate();
    let bc = b.certificate();
    let helper = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../service/tools/direct_binding_proof.py");
    let python = std::env::var("MESH_DIRECT_BINDING_PYTHON")
        .expect("CI must configure the Python service runtime for the binding proof");
    let output = Command::new(python)
        .arg(helper)
        .arg(hex(ac.as_ref()))
        .arg(hex(bc.as_ref()))
        .output()
        .expect("start protected-service binding proof");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    // The helper emits the exact authorized public certificate pins. Neither
    // process exports a private key and no local network control port exists.
    let expected = format!("{}\n{}\n", hex(ac.as_ref()), hex(bc.as_ref()));
    assert_eq!(
        String::from_utf8(output.stdout)
            .unwrap()
            .replace("\r\n", "\n"),
        expected
    );
    let a = Peer::bind("127.0.0.1:0".parse().unwrap(), a, bc).unwrap();
    let b = Peer::bind("127.0.0.1:0".parse().unwrap(), b, ac).unwrap();
    let (ap, bp) = tokio::join!(a.connect(b.address().unwrap()), b.accept());
    let (ap, bp) = (ap.unwrap(), bp.unwrap());
    let packet = Bytes::from_static(b"RNS-bound native transport proof");
    ap.send(packet.clone()).unwrap();
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), bp.receive())
            .await
            .unwrap()
            .unwrap(),
        packet
    );
}
