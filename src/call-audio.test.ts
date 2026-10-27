import { describe, expect, it, vi } from "vitest";

const audio = vi.hoisted(() => ({ begin: vi.fn(), end: vi.fn() }));
vi.mock("./api", () => ({ beginCallAudio: audio.begin, endCallAudio: audio.end }));
import { acquireCallAudio, releaseCallAudio } from "./call-audio";

describe("call audio ownership", () => {
  it("orders cancellation behind a pending acquisition and fences late cleanup", async () => {
    let finish!: (result: { granted: boolean }) => void;
    audio.begin.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue({ granted: true });
    audio.end.mockResolvedValue({ active: false });
    const oldCall = {};
    const newCall = {};
    const opening = acquireCallAudio(oldCall, "audio");
    await Promise.resolve();
    const cancelling = releaseCallAudio(oldCall);
    const replacing = acquireCallAudio(newCall, "video");
    expect(audio.begin).toHaveBeenCalledTimes(1);
    finish({ granted: true });
    await Promise.all([opening, cancelling, replacing]);
    expect(audio.end).toHaveBeenCalledTimes(1);
    expect(audio.begin).toHaveBeenLastCalledWith("video");
    await releaseCallAudio(oldCall);
    expect(audio.end).toHaveBeenCalledTimes(1);
    await releaseCallAudio(newCall);
    expect(audio.end).toHaveBeenCalledTimes(2);
  });
});
