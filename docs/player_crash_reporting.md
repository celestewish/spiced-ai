# Player Crash & Error Reporting — the contract your shipped game can call

Spiced's Known Issues panel (Testing screen) can show crashes real players
hit after you've shipped, tagged **"from players"** alongside bugs found
during your own development. Spiced does not provide a game-side SDK — this
document describes the plain HTTP contract your own game's crash handler
calls directly. Wiring it into your engine's exception/crash hooks is your
own integration work, the same as `docs/save_load_integrity_hook.md`
documents an external contract rather than shipping a Unity package.

## Availability constraint

This only works for a project that has opted into **Small-Team Mode** and
**linked a team** (Projects screen → Team). That's the only way Spiced's
backend has a `project_uuid` it recognizes at all — a solo/local-only
project never mints one, so there is nothing reachable outside your machine
to report against. This is consistent with Spiced's local-first-by-default
design, not an arbitrary restriction: if you never opted into Small-Team
Mode, nothing about your project is reachable from the internet, including
this endpoint.

To get your `project_uuid`: link the project to a team from the Projects
screen. Spiced shows the linked project's id there once linking succeeds.

## The endpoint

```
POST https://<your-spiced-backend-host>/projects/{project_uuid}/player-crashes
```

- **No authentication required.** Players don't have Spiced accounts, and
  Spiced doesn't want them to need one just to report a crash.
- Only works if `project_uuid` is currently linked to a Small-Team Mode
  team; otherwise you'll get `404 Not Found`.
- Payload sizes are capped server-side — see below. Sending more than the
  cap doesn't error; the extra content is silently truncated (except for
  wildly oversized requests, which are rejected outright before that point).

### Request body (JSON)

| Field           | Type            | Required | Cap (stored)   | Notes |
|-----------------|-----------------|----------|----------------|-------|
| `error_type`    | string          | yes      | 200 chars      | e.g. `"NullReferenceException"` |
| `message`       | string          | yes      | 2000 chars     | short, human-readable |
| `stack_excerpt` | string or null  | no       | 4000 chars     | a trimmed stack trace, never the full log |
| `app_version`   | string or null  | no       | 100 chars      | your game's own version string |
| `occurred_at`   | ISO 8601 string | yes      | —              | when the crash happened on the player's machine |

Example:

```json
{
  "error_type": "NullReferenceException",
  "message": "Object reference not set to an instance of an object at InventoryManager.AddItem",
  "stack_excerpt": "at InventoryManager.AddItem (Item item) [0x0002a] in InventoryManager.cs:47\nat PlayerController.PickUp...",
  "app_version": "1.2.0",
  "occurred_at": "2026-08-04T21:13:05Z"
}
```

Response: `201 Created` with the stored report (including a server-minted
`id`) — your game doesn't need to do anything with the response body; a
non-2xx status is the only thing worth checking for (and worth swallowing,
not retrying aggressively — see privacy/opt-in notes below).

### Minimal C# sketch (Unity)

```csharp
[Serializable]
private class CrashReportBody
{
    public string error_type;
    public string message;
    public string stack_excerpt;
    public string app_version;
    public string occurred_at;
}

IEnumerator ReportCrash(string errorType, string message, string stackExcerpt)
{
    if (!PlayerCrashReportingEnabled) yield break; // see opt-in note below

    var body = new CrashReportBody
    {
        error_type = errorType,
        message = message,
        stack_excerpt = stackExcerpt,
        app_version = Application.version,
        occurred_at = DateTime.UtcNow.ToString("o"),
    };
    var json = JsonUtility.ToJson(body);
    var request = new UnityWebRequest(
        $"{SpicedBackendHost}/projects/{ProjectUuid}/player-crashes", "POST");
    byte[] payload = System.Text.Encoding.UTF8.GetBytes(json);
    request.uploadHandler = new UploadHandlerRaw(payload);
    request.downloadHandler = new DownloadHandlerBuffer();
    request.SetRequestHeader("Content-Type", "application/json");
    yield return request.SendWebRequest();
    // Ignore the result either way — a failed report should never affect
    // the player's session, and there's nothing actionable to retry for.
}
```

## Privacy and opt-in expectations for your shipped game

Spiced only provides the receiving endpoint — **you** decide what your game
sends and whether players can turn it off, same as any other telemetry you
might add. A few expectations worth following, mirroring Spiced's own
"you stay in control" philosophy:

- **Tell players this exists**, ideally with an opt-out, the same way you'd
  disclose any other telemetry. Nothing here requires you to make it opt-in
  by default, but Spiced strongly recommends it — this is player data
  leaving their machine.
- **Never include personal information.** The schema has no field for a
  player's name, email, IP, or account id, and none should be smuggled into
  `message` or `stack_excerpt` either.
- **Keep `stack_excerpt` to what's useful for debugging** — a trimmed stack
  trace, not a full memory dump or save-file contents.
- Reports land in Spiced's Known Issues panel for whoever your team has
  invited to that project (Small-Team Mode members only) — this is not a
  public bug tracker.

## What this does and doesn't do

- It gives your team a lightweight way to see real-world crashes without
  building your own crash-reporting backend.
- It does **not** deduplicate on your end — send one report per crash
  occurrence; Spiced's own signature-matching (the same system used for
  crashes found during development) groups similar reports together and
  matches them against issues your team already knows about.
- It does **not** retry or queue anything for you — a failed POST (offline
  player, blocked network) is simply a report that never arrives. If you
  want retry/queueing behavior, that's your own integration to add.
