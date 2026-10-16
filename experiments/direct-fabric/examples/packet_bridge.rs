//! CI-only two-peer packet bridge over inherited anonymous pipes. Never shipped
//! or exposed through app commands. Python authorizes public certificate pins
//! before the harness permits either native peer to establish its path.
use bytes::Bytes;
use mesh_direct_proof::{Peer, SessionKey, MAX_PACKET};
use std::io::{Read, Write};

fn frame(writer: &mut impl Write, peer: u8, data: &[u8]) -> std::io::Result<()> {
    let size = u16::try_from(data.len()).expect("bounded proof frame");
    writer.write_all(&[peer])?;
    writer.write_all(&size.to_be_bytes())?;
    writer.write_all(data)?;
    writer.flush()
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a = SessionKey::generate().map_err(|_| "session key")?;
    let b = SessionKey::generate().map_err(|_| "session key")?;
    let ac = a.certificate();
    let bc = b.certificate();
    frame(&mut std::io::stdout(), 3, ac.as_ref())?;
    frame(&mut std::io::stdout(), 4, bc.as_ref())?;
    // A bounded pipe receiver is the only input channel. No TCP/UDP control
    // listener exists, and input cannot select a remote socket address.
    let (sender, mut input) = tokio::sync::mpsc::channel(128);
    std::thread::spawn(move || {
        let mut stdin = std::io::stdin().lock();
        loop {
            let mut header = [0; 3];
            if stdin.read_exact(&mut header).is_err() {
                break;
            }
            let size = u16::from_be_bytes([header[1], header[2]]) as usize;
            if header[0] > 2 || size == 0 || size > MAX_PACKET {
                break;
            }
            let mut packet = vec![0; size];
            if stdin.read_exact(&mut packet).is_err()
                || sender
                    .blocking_send((header[0], Bytes::from(packet)))
                    .is_err()
            {
                break;
            }
        }
    });
    let authorized = tokio::time::timeout(std::time::Duration::from_secs(30), input.recv()).await?;
    if authorized != Some((2, Bytes::from_static(b"authorized"))) {
        return Err("missing trusted-harness authorization".into());
    }
    let a = Peer::bind("127.0.0.1:0".parse()?, a, bc).map_err(|_| "bind")?;
    let b = Peer::bind("127.0.0.1:0".parse()?, b, ac).map_err(|_| "bind")?;
    let (ap, bp) = tokio::join!(a.connect(b.address().map_err(|_| "address")?), b.accept());
    let ap = ap.map_err(|_| "connect")?;
    let bp = bp.map_err(|_| "accept")?;
    frame(&mut std::io::stdout(), 2, b"ready")?;
    let (output, frames) = std::sync::mpsc::sync_channel::<(u8, Bytes)>(128);
    std::thread::spawn(move || {
        let mut stdout = std::io::stdout().lock();
        for (peer, packet) in frames {
            if frame(&mut stdout, peer, &packet).is_err() {
                break;
            }
        }
    });
    loop {
        tokio::select! {
            incoming = input.recv() => match incoming {
                Some((0, packet)) => { let _ = ap.send(packet); }
                Some((1, packet)) => { let _ = bp.send(packet); }
                _ => break,
            },
            packet = ap.receive() => match packet {
                Ok(packet) => { let _ = output.try_send((0, packet)); }
                Err(_) => break,
            },
            packet = bp.receive() => match packet {
                Ok(packet) => { let _ = output.try_send((1, packet)); }
                Err(_) => break,
            },
        }
    }
    a.close();
    b.close();
    Ok(())
}
