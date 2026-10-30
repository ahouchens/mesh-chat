/** Private WebView transport operations. No signaling, authority or peer retry policy. */
import { fingerprint } from "./webrtc-sdp";
import { adapterEpoch, descriptionHash } from "./native-carrier-evidence";

export interface TransportEvent { event: string; resource: string; data: string }
export interface ChannelPurpose { label: string; binary: boolean; ordered: boolean }
export interface CreateTransport {
  resource: string;
  ice: RTCConfiguration;
  channels: ChannelPurpose[];
}

type Allocation = {
  resource: string;
  pc: RTCPeerConnection;
  purposes: Set<string>;
  channels: Map<string, RTCDataChannel>;
  abort: AbortController;
  creating: boolean;
  closed: boolean;
  disposalFailed: boolean;
  packetDrops: number;
  icePolicy: RTCIceTransportPolicy;
  operations: number;
  revision: number;
};

const PURPOSES = new Set(["mesh-reticulum", "meshchat-reconnect", "mesh-onboarding"]);
const PACKET_LIMIT = 1064;
const CONTROL_LIMIT = 65536;
const BUFFER_LIMIT = 256 * 1024;
const OPERATION_TIMEOUT = 25000;
const FAILURES = new Set(["transport_retired", "transport_timeout", "invalid_local_sdp"]);
const bytes = (text: string) => new TextEncoder().encode(text);
const encoded = (value: Uint8Array) => btoa(Array.from(value, byte => String.fromCharCode(byte)).join(""));

export class DesktopTransport {
  private readonly allocations = new Map<string, Allocation>();
  private quarantined = false;
  private pendingOperations = 0;
  private readonly adapterEpoch = adapterEpoch();

  constructor(
    private readonly emit: (event: TransportEvent) => boolean,
    private readonly createPeer = (configuration: RTCConfiguration) => new RTCPeerConnection(configuration),
  ) {}

  createOffer(options: CreateTransport): Promise<{ sdp: string; fingerprint: string }> {
    return this.create(options);
  }

  acceptOffer(options: CreateTransport, offer: string): Promise<{ sdp: string; fingerprint: string }> {
    if (!offer || bytes(offer).length > CONTROL_LIMIT) return Promise.reject(new Error("invalid_sdp"));
    return this.create(options, offer);
  }

  async applyAnswer(resource: string, answer: string): Promise<void> {
    const allocation = this.require(resource);
    if (!answer || bytes(answer).length > CONTROL_LIMIT) throw new Error("invalid_sdp");
    await this.bounded(allocation, () => allocation.pc.setRemoteDescription({ type: "answer", sdp: answer }));
    this.check(allocation);
  }

  inspect(resource: string) {
    const allocation = this.allocations.get(resource);
    if (!allocation || allocation.closed) return null;
    return {
      ice_connection_state: allocation.pc.iceConnectionState,
      ice_gathering_state: allocation.pc.iceGatheringState,
      signaling_state: allocation.pc.signalingState,
      data_channel_state: allocation.channels.get("mesh-reticulum")?.readyState ?? "connecting",
      packet_drops: allocation.packetDrops,
    };
  }

  async inventory() {
    if (this.quarantined) throw new Error("transport_quarantined");
    if (this.pendingOperations >= 16) throw new Error("transport_capacity");
    this.pendingOperations++;
    try {
      const allocations = [...this.allocations.values()].filter(allocation => !allocation.closed);
      const snapshots = allocations.map(allocation => this.observation(allocation));
      const resources = await Promise.all(snapshots.map(async snapshot => {
        const { local, remote, revision: _revision, ...observation } = snapshot;
        return { ...observation, local_type: local?.type ?? null, remote_type: remote?.type ?? null,
          local_sdp_sha256: await descriptionHash(local?.sdp), remote_sdp_sha256: await descriptionHash(remote?.sdp) };
      }));
      if (this.quarantined || allocations.length !== this.allocations.size || allocations.some((allocation, index) =>
        !this.current(allocation) || JSON.stringify(this.observation(allocation)) !== JSON.stringify(snapshots[index]))) {
        throw new Error("transport_observation_changed");
      }
      return { v: 1, adapter_epoch: this.adapterEpoch, resources };
    } finally { this.pendingOperations--; }
  }

  private observation(allocation: Allocation) {
    const pc = allocation.pc;
    const local = pc.localDescription;
    const remote = pc.remoteDescription;
    return { resource: allocation.resource, ice_policy: allocation.icePolicy, revision: allocation.revision,
      pending: allocation.creating || allocation.operations > 0, ice_connection_state: pc.iceConnectionState,
      signaling_state: pc.signalingState,
      data_channel_state: allocation.channels.get("mesh-reticulum")?.readyState ?? "connecting",
      channels: [...allocation.channels].sort(([left], [right]) => left.localeCompare(right))
        .map(([label, channel]) => ({ label, state: channel.readyState })),
      local: local ? { type: local.type, sdp: local.sdp } : null,
      remote: remote ? { type: remote.type, sdp: remote.sdp } : null };
  }

  send(resource: string, packet: Uint8Array): boolean {
    if (!packet.length || packet.length > PACKET_LIMIT) return false;
    return this.sendChannel(resource, "mesh-reticulum", packet, packet.byteLength);
  }

  sendControl(resource: string, label: string, text: string): boolean {
    if (!PURPOSES.has(label) || label === "mesh-reticulum" || !text || text.length > CONTROL_LIMIT) return false;
    const length = bytes(text).length;
    return length <= CONTROL_LIMIT && this.sendChannel(resource, label, text, length);
  }

  close(resource: string): void {
    const allocation = this.allocations.get(resource);
    if (!allocation || allocation.closed) return;
    allocation.closed = true;
    allocation.abort.abort();
    try {
      allocation.pc.close();
    } catch {
      allocation.disposalFailed = true;
      this.quarantine();
      throw new Error("transport_disposal_failed");
    }
    this.release(allocation);
    this.deliver(allocation, "closed", "", false);
  }

  closeAll(): void {
    for (const resource of this.allocations.keys()) {
      try { this.close(resource); } catch { /* Failed disposal retains its reservation. */ }
    }
  }

  private async create(options: CreateTransport, offer?: string) {
    this.validate(options);
    if (this.quarantined) throw new Error("transport_quarantined");
    if (this.allocations.has(options.resource) || this.allocations.size >= 16) throw new Error("transport_capacity");
    const allocation: Allocation = {
      resource: options.resource, pc: this.openPeer(options.ice), purposes: new Set(options.channels.map(channel => channel.label)),
      channels: new Map(), abort: new AbortController(), creating: true, closed: false, disposalFailed: false, packetDrops: 0,
      icePolicy: options.ice.iceTransportPolicy!, operations: 0, revision: 0,
    };
    this.allocations.set(options.resource, allocation);
    this.observe(allocation);
    try {
      return await this.bounded(allocation, async () => {
        if (offer !== undefined) {
          await allocation.pc.setRemoteDescription({ type: "offer", sdp: offer });
          this.check(allocation);
        } else {
          for (const channel of options.channels) this.bindChannel(allocation,
            allocation.pc.createDataChannel(channel.label, { ordered: true }));
        }
        const description = offer === undefined ? await allocation.pc.createOffer() : await allocation.pc.createAnswer();
        this.check(allocation);
        await allocation.pc.setLocalDescription(description);
        this.check(allocation);
        await this.gather(allocation);
        this.check(allocation);
        const sdp = allocation.pc.localDescription?.sdp;
        if (!sdp || bytes(sdp).length > CONTROL_LIMIT || sdp.split(/\r?\n/).filter(line => line.startsWith("a=fingerprint:")).length !== 1) {
          throw new Error("invalid_local_sdp");
        }
        return { sdp, fingerprint: fingerprint(sdp) };
      });
    } catch (error) {
      this.close(allocation.resource);
      throw error;
    } finally {
      allocation.creating = false;
      this.release(allocation);
    }
  }

  private openPeer(configuration: RTCConfiguration) {
    try { return this.createPeer(configuration); }
    catch { throw new Error("transport_failed"); }
  }

  private validate(options: CreateTransport) {
    if (typeof options.resource !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(options.resource)) throw new Error("invalid_resource");
    if (!Array.isArray(options.channels) || !options.channels.length || options.channels.length > 3 ||
        options.channels.some(channel => !channel || typeof channel !== "object") ||
        new Set(options.channels.map(channel => channel.label)).size !== options.channels.length ||
        !options.channels.some(channel => channel.label === "mesh-reticulum") ||
        options.channels.some(channel => !PURPOSES.has(channel.label) || channel.ordered !== true ||
          channel.binary !== (channel.label === "mesh-reticulum"))) throw new Error("invalid_channels");
    if (!options.ice || !["all", "relay"].includes(options.ice.iceTransportPolicy ?? "") ||
        bytes(JSON.stringify(options.ice)).length > CONTROL_LIMIT) throw new Error("invalid_ice");
  }

  private observe(allocation: Allocation) {
    for (const [name, event, state] of [
      ["iceconnectionstatechange", "ice", () => allocation.pc.iceConnectionState],
      ["icegatheringstatechange", "gathering", () => allocation.pc.iceGatheringState],
      ["signalingstatechange", "signaling", () => allocation.pc.signalingState],
    ] as const) allocation.pc.addEventListener(name, () => {
      allocation.revision++;
      if (this.current(allocation)) this.deliver(allocation, event, state(), false);
    });
    allocation.pc.addEventListener("datachannel", event => this.bindChannel(allocation, event.channel));
  }

  private bindChannel(allocation: Allocation, channel: RTCDataChannel) {
    if (!this.current(allocation) || !allocation.purposes.has(channel.label) || allocation.channels.has(channel.label) ||
        !channel.ordered || channel.maxRetransmits !== null || channel.maxPacketLifeTime !== null) {
      channel.close();
      return;
    }
    allocation.channels.set(channel.label, channel);
    allocation.revision++;
    channel.binaryType = "arraybuffer";
    for (const event of ["open", "close", "error"] as const) channel.addEventListener(event, () => {
      if (!this.current(allocation)) return;
      allocation.revision++;
      this.deliver(allocation, "channel", `${channel.label}:${channel.readyState}`, false);
      if (event === "open" && channel.label === "mesh-reticulum" && this.current(allocation)) {
        this.deliver(allocation, "open", "", false);
      }
    });
    channel.addEventListener("message", event => {
      if (!this.current(allocation)) return;
      if (channel.label === "mesh-reticulum") {
        if (!(event.data instanceof ArrayBuffer) || !event.data.byteLength || event.data.byteLength > PACKET_LIMIT) {
          allocation.packetDrops++;
          return;
        }
        this.deliver(allocation, "message", encoded(new Uint8Array(event.data)), true);
      } else if (typeof event.data === "string" && event.data.length <= CONTROL_LIMIT && bytes(event.data).length <= CONTROL_LIMIT) {
        this.deliver(allocation, "control", `${channel.label}:${encoded(bytes(event.data))}`, false);
      } else {
        this.quarantine();
      }
    });
  }

  private deliver(allocation: Allocation, event: string, data: string, bulk: boolean) {
    let accepted = false;
    try { accepted = this.emit({ event, resource: allocation.resource, data }); } catch { /* Admission failure is handled below. */ }
    if (!accepted) {
      if (bulk) allocation.packetDrops++;
      else this.quarantine();
    }
  }

  private quarantine() {
    if (this.quarantined) return;
    this.quarantined = true;
    this.closeAll();
  }

  private sendChannel(resource: string, label: string, value: string | Uint8Array, length: number) {
    const allocation = this.allocations.get(resource);
    const channel = allocation?.channels.get(label);
    if (!allocation || !this.current(allocation) || channel?.readyState !== "open" ||
        channel.bufferedAmount + length > BUFFER_LIMIT) return false;
    try {
      if (typeof value === "string") channel.send(value);
      else channel.send(new Uint8Array(value));
      return true;
    } catch { return false; }
  }

  private require(resource: string) {
    const allocation = this.allocations.get(resource);
    if (!allocation || !this.current(allocation)) throw new Error("transport_retired");
    return allocation;
  }

  private current(allocation: Allocation) {
    return !allocation.closed && this.allocations.get(allocation.resource) === allocation;
  }

  private check(allocation: Allocation) {
    if (!this.current(allocation)) throw new Error("transport_retired");
  }

  private release(allocation: Allocation) {
    if (allocation.closed && !allocation.creating && !allocation.disposalFailed &&
        this.allocations.get(allocation.resource) === allocation) this.allocations.delete(allocation.resource);
  }

  private bounded<T>(allocation: Allocation, operation: () => Promise<T>): Promise<T> {
    if (allocation.operations > 0) return Promise.reject(new Error("transport_resource_busy"));
    if (this.pendingOperations >= 16) return Promise.reject(new Error("transport_capacity"));
    this.pendingOperations++;
    allocation.operations++;
    allocation.revision++;
    return new Promise<T>((resolve, reject) => {
      let completed = false;
      const signal = allocation.abort.signal;
      const aborted = () => { cleanup(); reject(new Error("transport_retired")); };
      const timer = setTimeout(() => {
        cleanup();
        try { this.close(allocation.resource); } catch { /* The host remains quarantined on failed disposal. */ }
        reject(new Error("transport_timeout"));
      }, OPERATION_TIMEOUT);
      const cleanup = () => {
        if (completed) return;
        completed = true;
        this.pendingOperations--;
        allocation.operations--;
        allocation.revision++;
        clearTimeout(timer);
        signal.removeEventListener("abort", aborted);
      };
      signal.addEventListener("abort", aborted, { once: true });
      if (signal.aborted) { aborted(); return; }
      Promise.resolve().then(() => { this.check(allocation); return operation(); }).then(
        value => { cleanup(); resolve(value); },
        error => { cleanup(); reject(new Error(error instanceof Error && FAILURES.has(error.message) ? error.message : "transport_failed")); },
      );
    });
  }

  private gather(allocation: Allocation): Promise<void> {
    if (allocation.pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve, reject) => {
      const signal = allocation.abort.signal;
      const cleanup = () => {
        allocation.pc.removeEventListener("icegatheringstatechange", changed);
        signal.removeEventListener("abort", aborted);
      };
      const changed = () => {
        if (allocation.pc.iceGatheringState === "complete") { cleanup(); resolve(); }
      };
      const aborted = () => { cleanup(); reject(new Error("transport_retired")); };
      allocation.pc.addEventListener("icegatheringstatechange", changed);
      signal.addEventListener("abort", aborted, { once: true });
      if (signal.aborted) aborted(); else changed();
    });
  }
}
