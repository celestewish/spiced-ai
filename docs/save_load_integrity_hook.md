# Save/Load Integrity Testing — the hook your game needs to implement

Spiced's Save Compatibility check (Testing screen) can only test a *built
game executable* that implements this small contract. It does not — and
cannot — inspect an unmodified game binary; there is no generic way to ask
an arbitrary executable "did that save load correctly?" from the outside.

If your game doesn't implement this hook, Spiced will still launch it once
per save file and wait, but every run will be reported as "couldn't tell"
(status `error`) because no result file ever appears.

## The contract

1. **On startup**, check for two environment variables:
   - `SPICED_LOAD_TEST_SAVE_PATH` — absolute path to the save file to load.
   - `SPICED_LOAD_TEST_RESULT_PATH` — absolute path to write your result to.

   If either is missing, start up normally — you're not being tested.

2. If both are present, **attempt to load the save** at
   `SPICED_LOAD_TEST_SAVE_PATH` exactly as you would during normal gameplay.

3. **Write a small JSON file** to `SPICED_LOAD_TEST_RESULT_PATH`:

   ```json
   { "success": true, "error": null }
   ```

   or, on failure:

   ```json
   { "success": false, "error": "Inventory array had 3 items, expected 4." }
   ```

   - `success` (required): boolean.
   - `error` (required, may be `null`): a short, human-readable string
     describing what went wrong when `success` is `false`. Ignored when
     `success` is `true`.

4. **Exit.** Any exit code is fine — Spiced does not use your exit code to
   decide pass/fail (a game can legitimately exit non-zero after a clean
   shutdown, or exit 0 after silently failing to load something). Only the
   JSON result file is read. If your process exits without that file ever
   appearing, Spiced reports the run as "couldn't tell" rather than guessing.

5. Spiced gives each save file up to **60 seconds by default** to finish.
   A save that hangs (an infinite load, a stuck dialog) is reported as
   `timed_out`, distinct from a real load failure.

## Minimal C# sketch (Unity)

```csharp
void Start()
{
    string savePath = Environment.GetEnvironmentVariable("SPICED_LOAD_TEST_SAVE_PATH");
    string resultPath = Environment.GetEnvironmentVariable("SPICED_LOAD_TEST_RESULT_PATH");
    if (string.IsNullOrEmpty(savePath) || string.IsNullOrEmpty(resultPath))
    {
        return; // not a Spiced test run — start normally
    }

    string json;
    try
    {
        LoadGame(savePath); // your own save-loading code
        json = "{\"success\":true,\"error\":null}";
    }
    catch (Exception ex)
    {
        json = "{\"success\":false,\"error\":\"" + ex.Message.Replace("\"", "'") + "\"}";
    }
    File.WriteAllText(resultPath, json);
    Application.Quit();
}
```

## What this does and doesn't tell you

- It tells you whether *your own load code* reported success for each save
  file you point Spiced at — a regression check across a folder of old
  saves as your save format evolves.
- It does **not** verify game *state* after loading (e.g. "is the player's
  gold actually correct?") unless your own `LoadGame` logic already checks
  that and reports it as a failure.
- It never modifies, uploads, or reads the save files' contents itself —
  Spiced only passes the path and lets your game do the loading.
