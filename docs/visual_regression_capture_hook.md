# Visual Regression Testing — the marker-GameObject convention

Spiced's Visual Regression Testing (Shaders/VFX screen, "Live Capture")
screenshots a fixed list of "key scenes" each run and flags scenes that
changed noticeably since the previous run. To do that, it needs to know
*where to put the camera* in each scene — this doc explains the convention
it uses instead of asking you to type raw position/rotation numbers.

## The convention

For each key scene you want Spiced to capture:

1. **Place an empty GameObject** anywhere in that scene, positioned and
   rotated exactly where you want the capture camera to be (e.g. drop one
   into your main hall scene, aim it at the room, name it something like
   `SpicedCapture_MainHall`).
2. **Register the key scene in Spiced** (Shaders/VFX screen → Visual
   Regression Testing (Live Capture) → Add key scene): the scene's asset
   path (e.g. `Assets/Scenes/MainHall.unity`), a label of your choice, and
   that GameObject's exact name.
3. On each capture run, Spiced opens the scene in a headless Unity Editor,
   finds the GameObject by name (`GameObject.Find`), snaps a temporary
   capture camera to its transform, renders a 1920×1080 screenshot, and
   closes it back out. Your marker GameObject itself is never modified or
   removed.

If the named GameObject isn't found in the scene, that one key scene is
reported as a capture error (severity `error`) — the rest of the run's key
scenes still capture normally.

## Why a marker instead of raw coordinates

A GameObject you can see and drag around in the Unity Editor is much easier
to get right than typing XYZ position/rotation floats into a text field, and
it survives scene edits (move the marker, the next capture just follows it)
without you having to update anything in Spiced.

## Requirements

- A Unity Editor install Spiced can launch headlessly (same requirement as
  the Automated Build Pipeline and Unity Test Runner features).
- Spiced writes `Assets/Editor/SpicedVisualCaptureScript.cs` into your
  project the first time it runs a capture, and keeps it up to date on every
  run after that — don't hand-edit it, your changes will be overwritten.
