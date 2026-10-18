import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FileUp, QrCode, Settings, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { pickInvitationFile, runtimePlatform } from "./api";
import {
  createInvitationQrValue,
  InvitationTransferError,
  MAX_INVITATION_DOCUMENT_BYTES,
  normalizeInvitationInput,
} from "./invitation-transfer";

type ImportSource = "file" | "image" | "camera";

function sourceLabel(source: ImportSource): string {
  if (source === "file") return "Invitation file loaded.";
  if (source === "image") return "QR image read.";
  return "Invitation scanned.";
}

function transferMessage(reason: unknown, fallback: string): string {
  if (reason instanceof InvitationTransferError) return reason.message;
  if (reason && typeof reason === "object" && "code" in reason && typeof reason.code === "string") {
    const messages: Record<string, string> = {
      invitation_file_type_invalid: "That is not a supported Mesh Chat invitation file.",
      invitation_file_too_large: "That invitation file is larger than Mesh Chat can open safely.",
      invitation_file_encoding_invalid: "That invitation file is not valid UTF-8 text.",
      invitation_file_invalid: "That file does not contain a complete Mesh Chat invitation or connection document.",
      invitation_file_unavailable: "Android could not read the selected invitation file.",
    };
    return messages[reason.code] ?? fallback;
  }
  return fallback;
}

async function readBrowserFile(file: File): Promise<string> {
  if (file.size > MAX_INVITATION_DOCUMENT_BYTES) {
    throw new InvitationTransferError("This invitation file is too large for Mesh Chat to open safely.");
  }
  const value = await file.text();
  if (new TextEncoder().encode(value).byteLength > MAX_INVITATION_DOCUMENT_BYTES) {
    throw new InvitationTransferError("This invitation file is too large for Mesh Chat to open safely.");
  }
  return value;
}

export function InvitationImportActions({
  onValue,
  showTextFile = true,
}: {
  onValue: (value: string) => void;
  showTextFile?: boolean;
}) {
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [scanning, setScanning] = useState(false);
  const [openingFile, setOpeningFile] = useState(false);
  const [cameraSettingsAvailable, setCameraSettingsAvailable] = useState(false);
  const textFileRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const mobileCameraRef = useRef(false);
  const cameraStarting = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const acceptValue = async (raw: string, source: ImportSource) => {
    const value = await normalizeInvitationInput(raw);
    onValue(value);
    setError("");
    setStatus(sourceLabel(source));
  };

  const openFile = async () => {
    if (openingFile) return;
    setOpeningFile(true);
    setError("");
    setStatus("");
    try {
      if (await runtimePlatform() === "android") {
        const value = await pickInvitationFile();
        if (value !== null) await acceptValue(value, "file");
      } else {
        textFileRef.current?.click();
      }
    } catch (reason) {
      setError(transferMessage(reason, "Mesh Chat could not open that invitation file."));
    } finally {
      setOpeningFile(false);
    }
  };

  const chooseBrowserFile = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    setStatus("");
    try {
      await acceptValue(await readBrowserFile(file), "file");
    } catch (reason) {
      setError(transferMessage(reason, "Mesh Chat could not read that invitation file."));
    } finally {
      if (textFileRef.current) textFileRef.current.value = "";
    }
  };

  const scanImage = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    setStatus("");
    const url = URL.createObjectURL(file);
    try {
      const { BrowserQRCodeReader } = await import("@zxing/browser");
      const result = await new BrowserQRCodeReader().decodeFromImageUrl(url);
      await acceptValue(result.getText(), "image");
    } catch (reason) {
      setError(transferMessage(reason, "No Mesh Chat QR code was found in that image."));
    } finally {
      URL.revokeObjectURL(url);
    }
  };

  const startCamera = async () => {
    if (scanning) {
      setScanning(false);
      return;
    }
    if (cameraStarting.current) return;
    cameraStarting.current = true;
    setError("");
    setStatus("");
    setCameraSettingsAvailable(false);
    try {
      const platform = await runtimePlatform();
      mobileCameraRef.current = platform !== "desktop";
      if (platform !== "desktop") {
        const { checkPermissions, requestPermissions } = await import("@tauri-apps/plugin-barcode-scanner");
        let permission = await checkPermissions();
        if (permission !== "granted") permission = await requestPermissions();
        if (permission !== "granted") {
          setCameraSettingsAvailable(true);
          setError("Camera access is off. Allow Camera for Mesh Chat, then try again.");
          return;
        }
      }
      if (mounted.current) setScanning(true);
    } catch {
      setCameraSettingsAvailable(mobileCameraRef.current);
      setError("Mesh Chat could not start the camera. Check Camera permission and try again.");
    } finally {
      cameraStarting.current = false;
    }
  };

  const openCameraSettings = async () => {
    try {
      const { openAppSettings } = await import("@tauri-apps/plugin-barcode-scanner");
      await openAppSettings();
    } catch {
      setError("Open system settings and allow Camera for Mesh Chat.");
    }
  };

  useEffect(() => {
    if (!scanning) return;
    if (mobileCameraRef.current) {
      let active = true;
      let cancel: (() => Promise<void>) | undefined;
      document.documentElement.classList.add("native-qr-scanning");
      const timeout = setTimeout(() => {
        if (!active) return;
        setError("No QR code was read. Try again with the complete code visible and well lit.");
        setScanning(false);
      }, 60000);
      void (async () => {
        try {
          const scanner = await import("@tauri-apps/plugin-barcode-scanner");
          if (!active) return;
          cancel = scanner.cancel;
          const result = await scanner.scan({ windowed: true, cameraDirection: "back", formats: [scanner.Format.QRCode] });
          if (!active) return;
          await acceptValue(result.content, "camera");
        } catch (reason) {
          if (active) setError(transferMessage(reason, "The camera could not read a Mesh Chat QR code. Try again or open an invitation file."));
        } finally {
          if (active) setScanning(false);
        }
      })();
      return () => {
        active = false;
        clearTimeout(timeout);
        document.documentElement.classList.remove("native-qr-scanning");
        void cancel?.().catch(() => {});
      };
    }
    if (!videoRef.current) return;
    let active = true;
    let stop: (() => void) | undefined;
    void (async () => {
      try {
        const { BrowserQRCodeReader } = await import("@zxing/browser");
        const controls = await new BrowserQRCodeReader().decodeFromVideoDevice(
          undefined,
          videoRef.current ?? undefined,
          (result, _error, scanControls) => {
            if (!result || !active) return;
            active = false;
            // ZXing can decode the first frame before decodeFromVideoDevice's
            // promise resolves, so use the callback's already-live controls
            // instead of closing over the not-yet-assigned promise result.
            scanControls.stop();
            setScanning(false);
            void acceptValue(result.getText(), "camera").catch((reason) => {
              setError(transferMessage(reason, "That QR code is not a complete Mesh Chat invitation."));
            });
          },
        );
        if (!active) {
          controls.stop();
          return;
        }
        stop = () => controls.stop();
      } catch {
        if (!active) return;
        setError("The camera preview is unavailable. Check Camera permission and try again.");
        setCameraSettingsAvailable(mobileCameraRef.current);
        setScanning(false);
      }
    })();
    return () => {
      active = false;
      stop?.();
    };
  }, [scanning]);

  return (
    <div className="import-row">
      {showTextFile && <>
        <button className="file-action file-action--button" type="button" disabled={openingFile} onClick={() => void openFile()}><FileUp size={17} /> {openingFile ? "Opening…" : "Open invitation file"}</button>
        <input
          ref={textFileRef}
          className="visually-hidden-file"
          type="file"
          aria-label="Choose invitation file"
          onChange={(event) => void chooseBrowserFile(event.target.files?.[0])}
        />
      </>}
      <label className="file-action"><QrCode size={17} /> Read QR image<input type="file" accept="image/*" onChange={(event) => void scanImage(event.target.files?.[0])} /></label>
      <button className="file-action file-action--button" type="button" onClick={() => void startCamera()}>{scanning ? <X size={17} /> : <QrCode size={17} />} {scanning ? "Stop camera" : "Scan with camera"}</button>
      {cameraSettingsAvailable && <button className="file-action file-action--button" type="button" onClick={() => void openCameraSettings()}><Settings size={17} /> Camera settings</button>}
      {scanning && (mobileCameraRef.current ? createPortal(
        <div className="native-qr-overlay" role="dialog" aria-modal="true" aria-label="Scan invitation QR code">
          <p>Hold the full Mesh Chat QR code inside the camera view.</p>
          <button type="button" autoFocus onClick={() => setScanning(false)}><X size={20} /> Stop camera</button>
        </div>, document.body,
      ) : <div className="camera-box"><video ref={videoRef} muted playsInline aria-label="Camera preview" /><span>Hold the full Mesh Chat QR code inside the frame.</span></div>)}
      {status && <span className="import-status" role="status">{status}</span>}
      {error && <span className="form-error" role="alert">{error}</span>}
    </div>
  );
}

export function InvitationQrCode({
  document,
  destination,
}: {
  document: string;
  destination: "chat" | "workspace" | "connection reply" | "reconnect update";
}) {
  const [value, setValue] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    setValue(undefined);
    void createInvitationQrValue(document).then((created) => {
      if (active) setValue(created);
    });
    return () => { active = false; };
  }, [document]);

  return (
    <section className="invitation-qr" aria-label="Invitation QR code">
      <div>
        <strong>Scan with Mesh Chat</strong>
        <span>On the other device, open {destination === "workspace" ? "Join workspace" : "Open an invite"} and choose Scan with camera.</span>
      </div>
      {value === undefined && <p className="muted" role="status">Preparing a camera-friendly QR code…</p>}
      {value === null && <p className="direct-host-warning" role="status">This signed document is too large for one reliable QR code. Use Share or Save file instead.</p>}
      {value && <div className="qr-frame qr-frame--transfer"><QRCodeSVG value={value} size={600} level="L" boostLevel={false} marginSize={4} bgColor="#ffffff" fgColor="#10251e" /></div>}
    </section>
  );
}
