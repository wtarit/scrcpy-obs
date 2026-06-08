# scrcpy-obs — Known Issues

Snapshot as of 2026-04-17. Update as we resolve or reclassify.

## Blockers / Required work

### 1. First IDR is dropped by scrcpy stream-sink
**Symptom:** With default encoder settings, OBS source stays blank (black). `avformat_find_stream_info` reports `codec=h264 0x0`, decoder emits `non-existing PPS 0 referenced` and `no frame!` until a keyframe eventually arrives (or never).

**Root cause:** In `scrcpy/app/src/stream_sink.c::sc_stream_sink_init_template`, after the config packet (SPS/PPS) is consumed into `codecpar->extradata`, the init-phase queues are cleared:

```c
sink->template_ready = true;
sc_stream_sink_queue_clear(&sink->video_queue);
sc_stream_sink_queue_clear(&sink->audio_queue);
```

From that moment, `push` fans out directly to active client queues. But the main loop is still blocked in `avio_open2`, so no client exists yet. Every video packet produced between "template ready" and "first client connected" is dropped — including the very first IDR that MediaCodec emits right after the CSD.

The next IDR is `KEY_I_FRAME_INTERVAL` seconds later (default 10 s in `SurfaceEncoder.java`), and on some encoders (see #2) it is not emitted at all while the screen is static.

**Current workaround (in `src/scrcpy-source.c`):** we pass `--video-codec-options=i-frame-interval:int=1` so the encoder emits keyframes ~every second once content changes. Reduces the blank period to a few seconds on an active screen.

**Proper fix (choose one):**
- Patch scrcpy: hold packets in `sink->video_queue` until the first client connects, then drain into that client's queue, optionally dropping pre-keyframe packets. Needs an upstream-friendly PR against the `streamsink/vX.Y.Z` branch.
- Add a control-channel round-trip: drop `--no-control`, connect the control socket, send `SC_CONTROL_MSG_TYPE_RESET_VIDEO` immediately after the demuxer opens the TCP stream. Forces a fresh IDR on demand. More moving parts; more robust to reconnect.

### 2. Android 16 emulator MediaCodec ignores `KEY_I_FRAME_INTERVAL` on static content
**Symptom:** Even with `i-frame-interval=1`, a fully idle emulator screen produces zero keyframes in 10–20 s. All packets flagged non-key (`flags=___` in `ffprobe -show_packets`). Only appearing after real pixel changes does the encoder emit IDRs.

**Verified on:** `sdk_gphone64_x86_64`, Android 16, x86-64 emulator. Captured `app drawer` screen, swiped → first IDR ~1 s after activity.

**Implication:** Tests and demos must drive emulator input (e.g. adb `input swipe`) for the smoke test to succeed. A real device likely behaves better but untested.

**Fix:** Same as #1 — forcing RESET_VIDEO after connect sidesteps the dependence on content change.

### 3. Orphan demuxer threads keep retrying after a source is removed
**Symptom:** After `remove_input` via OBS WebSocket (or user deleting the source), OBS log keeps emitting `avformat_open_input(tcp://127.0.0.1:<old_port>): Error number -138 occurred` every ~5 s for up to ~3 min. Not user-visible but wasteful and confuses log diagnosis.

**Root cause:** `scrcpy_demuxer_destroy` sets `stop=true` and joins the thread, but the thread may be blocked inside `avformat_open_input` on a dead TCP socket. `rw_timeout=30s` caps each attempt; the retry loop runs up to 30 attempts. `pthread_join` waits the full stretch, OR — more likely here — OBS destroys the source asynchronously, so a second context holds the old thread alive briefly. Need to investigate which.

**Fix:** Wire the stop flag into an `AVIOInterruptCB` on the input context so `avformat_open_input` aborts promptly when the source is torn down.

## Non-blocking observations

### 4. `avformat_open_input` returns error `-138` on first attempt (ETIMEDOUT)
Expected: scrcpy-server needs a few seconds to boot the Android-side encoder and open the listen socket. Our retry loop handles it (up to 30 attempts, 0.5 s apart). Visible in OBS logs as 1–2 errors before `scrcpy-demuxer: reading ... stream` succeeds. Not a bug; informational.

### 5. OBS preview blank when launched with `--minimize-to-tray`
Not a plugin issue. `obs64.exe --minimize-to-tray` hides the main window to the system tray. The source does receive frames (verified via `GetSourceScreenshot` WebSocket request — see `tools/ws_grab.py`). Double-click the tray icon to show the main window.

### 6. Demuxer opens mid-stream and spams `send_packet: Invalid data` until first IDR
Each `send_packet` before the first IDR returns `AVERROR_INVALIDDATA`. Throttled to 5 lines (`kErrLogMax` in `src/scrcpy-demuxer.c`). Error path now flushes the decoder (`avcodec_flush_buffers`) so a subsequent IDR is accepted cleanly.

## Verified-working path (2026-04-17)

- Plugin installed at `C:\ProgramData\obs-studio\plugins\scrcpy-obs\`.
- Smoke test: `python tools/ws_smoke.py` — connects OBS WebSocket on 127.0.0.1:4455, creates `ScrcpyTest` scene + `ScrcpySmokeInput` source, drives emulator activity, captures 30 screenshots over 60 s. Expected: 29/30 unique hashes, first shot blank (pre-IDR), remainder containing live Android screen.
- Full-resolution capture: `python tools/ws_grab.py` saves 15 PNGs to `C:\Users\tarit\obs-shots\` showing live app drawer with visibly-advancing clock.
