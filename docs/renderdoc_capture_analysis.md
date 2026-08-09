# Shader Performance Profiling — the RenderDoc dependency

Spiced's Shader Performance Profiling (GPU Capture) (Shaders/VFX screen)
analyzes a [RenderDoc](https://renderdoc.org/) capture file (`.rdc`) to flag
shaders that are too expensive for a target hardware tier, using real
captured GPU time rather than a static heuristic.

## What Spiced does NOT do

Spiced does not launch your game, capture a frame, or install/configure
RenderDoc for you. **You make the capture yourself**, using RenderDoc's own
UI (or your own launch wrapper), and then point Spiced at the resulting
`.rdc` file.

This is a deliberate scope decision, not an oversight. Automating the
capture step itself — as the original design intent called for — would mean
baking a *runtime* trigger hook into your game's own built player (RenderDoc
captures a running standalone process, not the Unity Editor), launching
that build under `renderdoccmd capture`, and triggering the capture at the
right frame. That's a substantially larger, separate mechanism from
anything else in this feature set, and one Spiced hasn't built (or been
able to verify) yet.

## Important: this integration is not verified against a real RenderDoc install

Every other external engine integration in Spiced (Unity Editor scripts,
`ffmpeg`) was checked against a real, working installation before shipping.
RenderDoc was not available in the environment this feature was built in,
and GPU frame capture/replay likely wouldn't function in that kind of
sandboxed environment even with RenderDoc installed — it needs a real GPU
context.

The RenderDoc Python API calls this feature uses (`OpenCaptureFile`,
`ReplayController.GetDrawcalls`/`GetRootActions`, `FetchCounters` with
`GPUCounter.EventGPUDuration`) match RenderDoc's own published API
reference (https://renderdoc.org/docs/python_api/index.html) as closely as
could be determined without a capture to test against. Treat this as a
documented best effort, not a confirmed-working integration — **please
verify it against a real `.rdc` capture, and report back if the shader
names, GPU times, or bandwidth figures look wrong**, before relying on it
for real profiling decisions.

## Setup

1. Install RenderDoc from https://renderdoc.org/ (Windows-first, matching
   the rest of Spiced).
2. Make a capture of your game using RenderDoc's own UI (`qrenderdoc.exe`)
   — launch your game through RenderDoc, hit the capture hotkey (default
   `F12`/`PrtScn`) on the frame you want to profile, and save the resulting
   `.rdc` file.
3. In Spiced, point "Analyze capture" at that `.rdc` file, and at
   RenderDoc's `pymodules` directory (inside your RenderDoc install folder
   — this is what makes `import renderdoc` work; it must match the same
   Python ABI/version RenderDoc itself was built against, which may not be
   Spiced's own Python).
