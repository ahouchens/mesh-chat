import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  cameraStop: vi.fn(),
  createInvitationQrValue: vi.fn(),
  decodeFromVideoDevice: vi.fn(),
  pickInvitationFile: vi.fn(),
  qrCodeSvg: vi.fn((_props: Record<string, unknown>) => null),
  runtimePlatform: vi.fn(),
  nativeScan: vi.fn(),
  nativeCancel: vi.fn().mockResolvedValue(undefined),
  checkPermissions: vi.fn(),
  requestPermissions: vi.fn(),
}));

vi.mock("./api", () => ({
  pickInvitationFile: mocks.pickInvitationFile,
  runtimePlatform: mocks.runtimePlatform,
}));

vi.mock("./invitation-transfer", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./invitation-transfer")>();
  return { ...actual, createInvitationQrValue: mocks.createInvitationQrValue };
});

vi.mock("qrcode.react", () => ({ QRCodeSVG: mocks.qrCodeSvg }));
vi.mock("@tauri-apps/plugin-barcode-scanner", () => ({
  scan: mocks.nativeScan, cancel: mocks.nativeCancel,
  checkPermissions: mocks.checkPermissions, requestPermissions: mocks.requestPermissions,
  Format: { QRCode: "QR_CODE" },
}));

vi.mock("@zxing/browser", () => ({
  BrowserQRCodeReader: class {
    decodeFromVideoDevice(...args: unknown[]) {
      return mocks.decodeFromVideoDevice(...args);
    }
  },
}));

import { InvitationImportActions, InvitationQrCode } from "./InvitationTransfer";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("InvitationImportActions", () => {
  it("opens the native Android rear camera and imports a scanned invitation", async () => {
    const invitation = `MESHWORKSPACE4:${"abc_DEF-123".repeat(430)}`;
    mocks.runtimePlatform.mockResolvedValue("android");
    mocks.checkPermissions.mockResolvedValue("prompt");
    mocks.requestPermissions.mockResolvedValue("granted");
    mocks.nativeScan.mockResolvedValue({ content: invitation });
    const onValue = vi.fn();
    render(<InvitationImportActions onValue={onValue} />);
    fireEvent.click(screen.getByRole("button", { name: "Scan with camera" }));
    await waitFor(() => expect(onValue).toHaveBeenCalledWith(invitation));
    expect(mocks.nativeScan).toHaveBeenCalledWith({ windowed: true, cameraDirection: "back", formats: ["QR_CODE"] });
    expect(mocks.decodeFromVideoDevice).not.toHaveBeenCalled();
    await waitFor(() => expect(document.documentElement.classList.contains("native-qr-scanning")).toBe(false));
  });

  it("cancels an unfinished native scan when its dialog unmounts", async () => {
    mocks.runtimePlatform.mockResolvedValue("android");
    mocks.checkPermissions.mockResolvedValue("granted");
    mocks.nativeScan.mockImplementation(() => new Promise(() => {}));
    const { unmount } = render(<InvitationImportActions onValue={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Scan with camera" }));
    await waitFor(() => expect(mocks.nativeScan).toHaveBeenCalledTimes(1));
    expect(document.documentElement.classList.contains("native-qr-scanning")).toBe(true);
    unmount();
    expect(mocks.nativeCancel).toHaveBeenCalledTimes(1);
    expect(document.documentElement.classList.contains("native-qr-scanning")).toBe(false);
  });

  it("does not open a scanner when camera permission is denied", async () => {
    mocks.runtimePlatform.mockResolvedValue("android");
    mocks.checkPermissions.mockResolvedValue("denied");
    mocks.requestPermissions.mockResolvedValue("denied");
    render(<InvitationImportActions onValue={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Scan with camera" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Camera access is off");
    expect(mocks.nativeScan).not.toHaveBeenCalled();
    expect(mocks.decodeFromVideoDevice).not.toHaveBeenCalled();
  });

  it("opens Android's native invitation picker and returns the exact selected value", async () => {
    const invitation = `MESHWORKSPACE4:${"abc_DEF-123".repeat(430)}`;
    const onValue = vi.fn();
    mocks.runtimePlatform.mockResolvedValue("android");
    mocks.pickInvitationFile.mockResolvedValue(invitation);

    render(<InvitationImportActions onValue={onValue} />);
    fireEvent.click(screen.getByRole("button", { name: "Open invitation file" }));

    await waitFor(() => expect(mocks.pickInvitationFile).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onValue).toHaveBeenCalledWith(invitation));
    expect(screen.getByRole("status").textContent).toBe("Invitation file loaded.");
  });

  it("treats native picker cancellation as a quiet no-op", async () => {
    const onValue = vi.fn();
    mocks.runtimePlatform.mockResolvedValue("android");
    mocks.pickInvitationFile.mockResolvedValue(null);

    render(<InvitationImportActions onValue={onValue} />);
    const open = screen.getByRole("button", { name: "Open invitation file" });
    fireEvent.click(open);

    await waitFor(() => expect(mocks.pickInvitationFile).toHaveBeenCalledTimes(1));
    await waitFor(() => expect((open as HTMLButtonElement).disabled).toBe(false));
    expect(onValue).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an error when the native picker cannot open the selected document", async () => {
    const onValue = vi.fn();
    mocks.runtimePlatform.mockResolvedValue("android");
    mocks.pickInvitationFile.mockRejectedValue({ code: "invitation_file_invalid" });

    render(<InvitationImportActions onValue={onValue} />);
    fireEvent.click(screen.getByRole("button", { name: "Open invitation file" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("That file does not contain a complete Mesh Chat invitation or connection document.");
    expect(onValue).not.toHaveBeenCalled();
  });

  it("accepts a camera result delivered before scanner startup finishes", async () => {
    const invitation = `MESHWORKSPACE4:${"abc_DEF-123".repeat(430)}`;
    const onValue = vi.fn();
    mocks.runtimePlatform.mockResolvedValue("desktop");
    mocks.decodeFromVideoDevice.mockImplementation(async (
      _device: unknown,
      _video: unknown,
      callback: (result: { getText: () => string }, error: undefined, controls: { stop: () => void }) => void,
    ) => {
      const controls = { stop: mocks.cameraStop };
      callback({ getText: () => invitation }, undefined, controls);
      return controls;
    });

    render(<InvitationImportActions onValue={onValue} />);
    fireEvent.click(screen.getByRole("button", { name: "Scan with camera" }));

    await waitFor(() => expect(onValue).toHaveBeenCalledWith(invitation));
    expect(mocks.cameraStop).toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("Invitation scanned.");
  });
});

describe("InvitationQrCode", () => {
  it("renders a compact QR for a realistic long workspace invitation", async () => {
    const invitation = `MESHWORKSPACE4:${"abc_DEF-123".repeat(430)}`;
    const compact = `MESHQR1:${"compressed_workspace".repeat(40)}`;
    mocks.createInvitationQrValue.mockResolvedValue(compact);

    render(<InvitationQrCode document={invitation} destination="workspace" />);

    expect(screen.getByText(/Preparing a camera-friendly QR code/i)).toBeTruthy();
    await waitFor(() => expect(mocks.qrCodeSvg).toHaveBeenCalledTimes(1));
    expect(mocks.createInvitationQrValue).toHaveBeenCalledWith(invitation);
    expect(mocks.qrCodeSvg.mock.calls[0][0]).toEqual(expect.objectContaining({
      value: compact,
      size: 600,
      level: "L",
      boostLevel: false,
      marginSize: 4,
    }));
    expect(screen.getByText(/open Join workspace/i)).toBeTruthy();
    expect(screen.queryByText(/too large for one reliable QR code/i)).toBeNull();
  });
});
