//! CI-only two-peer packet bridge over inherited anonymous pipes. Never shipped
//! or exposed through app commands. Python authorizes public certificate pins
//! before the harness permits either native peer to establish its path.
use bytes::Bytes;
use mesh_direct_proof::{attempt::PreparedAttempt, BoundSocket, SessionKey, MAX_PACKET};
use std::io::{Read, Write};
use std::time::Duration;

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
    let mut ac = a.certificate();
    let bc = b.certificate();
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
    // Initialize exact local session/generation pairs before exporting keys.
    // This is a CI-only inherited-pipe protocol, not shipping service IPC.
    let Some((2, init)) = tokio::time::timeout(Duration::from_secs(30), input.recv()).await? else {
        return Err("missing session initialization".into());
    };
    if init.len() != 52 {
        return Err("invalid session initialization".into());
    }
    let mut a_session: [u8; 16] = init[..16].try_into()?;
    let mut a_generation = u64::from_be_bytes(init[16..24].try_into()?);
    let b_session: [u8; 16] = init[24..40].try_into()?;
    let b_generation = u64::from_be_bytes(init[40..48].try_into()?);
    let remaining = Duration::from_secs(u32::from_be_bytes(init[48..52].try_into()?) as u64);
    let authorization_deadline = tokio::time::Instant::now() + remaining;
    let mut a = PreparedAttempt::new(
        BoundSocket::bind("127.0.0.1:0".parse()?).map_err(|_| "bind")?,
        a,
        a_session,
        a_generation,
        remaining,
    )
    .map_err(|_| "prepare")?;
    let mut b = PreparedAttempt::new(
        BoundSocket::bind("127.0.0.1:0".parse()?).map_err(|_| "bind")?,
        b,
        b_session,
        b_generation,
        remaining,
    )
    .map_err(|_| "prepare")?;
    let (mut a_address, b_address) = (
        a.address().map_err(|_| "address")?,
        b.address().map_err(|_| "address")?,
    );
    frame(&mut std::io::stdout(), 3, ac.as_ref())?;
    frame(&mut std::io::stdout(), 4, bc.as_ref())?;
    let Some((2, mut authorized)) = tokio::time::timeout_at(
        authorization_deadline.min(tokio::time::Instant::now() + Duration::from_secs(30)),
        input.recv(),
    )
    .await?
    else {
        return Err("missing trusted-harness authorization".into());
    };
    let refreshed = authorized.len() == 57 && authorized[0] == b'R';
    if refreshed {
        // The owner has durably accepted the Answer. Retain the joiner's exact
        // socket/key while replacing only the owner's Offer credentials.
        b.start(b_session, b_generation, authorized[25..57].try_into()?)
            .map_err(|_| "save answer")?;
        let next_generation = u64::from_be_bytes(authorized[17..25].try_into()?);
        if next_generation <= a_generation {
            return Err("owner generation did not advance".into());
        }
        a_session = authorized[1..17].try_into()?;
        a_generation = next_generation;
        a.cancel();
        let key = SessionKey::generate().map_err(|_| "refresh key")?;
        ac = key.certificate();
        a = PreparedAttempt::new(
            BoundSocket::bind("127.0.0.1:0".parse()?).map_err(|_| "refresh bind")?,
            key,
            a_session,
            a_generation,
            authorization_deadline.saturating_duration_since(tokio::time::Instant::now()),
        )
        .map_err(|_| "refresh prepare")?;
        a_address = a.address().map_err(|_| "refresh address")?;
        frame(&mut std::io::stdout(), 3, ac.as_ref())?;
        let Some((2, ready)) =
            tokio::time::timeout_at(authorization_deadline, input.recv()).await?
        else {
            return Err("missing Ready authorization".into());
        };
        authorized = ready;
    }
    if authorized.len() != (if refreshed { 72 } else { 64 }) {
        return Err("invalid authorization digests".into());
    }
    // Digests name the local saved Ready/Answer, or admitted binding. The trusted
    // harness sends these only after the other service has accepted the peer.
    a.start(a_session, a_generation, authorized[..32].try_into()?)
        .map_err(|_| "arm")?;
    if refreshed {
        let ready_generation = u64::from_be_bytes(authorized[64..72].try_into()?);
        if ready_generation != a_generation {
            return Err("Ready generation differs from owned session".into());
        }
        b.rearm(
            authorized[32..64].try_into()?,
            ready_generation,
            authorized[..32].try_into()?,
        )
        .map_err(|_| "Ready rearm")?;
    } else {
        b.start(b_session, b_generation, authorized[32..64].try_into()?)
            .map_err(|_| "arm")?;
    }
    let a = a.into_peer(bc).map_err(|_| "activate")?;
    let b = b.into_peer(ac).map_err(|_| "activate")?;
    if a.address().map_err(|_| "address")? != a_address
        || b.address().map_err(|_| "address")? != b_address
    {
        return Err("candidate socket changed".into());
    }
    let remote_address = b.address().map_err(|_| "address")?;
    let (ap, bp) = tokio::time::timeout_at(authorization_deadline, async {
        tokio::join!(a.connect(remote_address), b.accept())
    })
    .await?;
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
            _ = tokio::time::sleep_until(authorization_deadline) => break,
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
