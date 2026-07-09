# Spiced

**A human-centered AI companion for indie game developers.**

Spiced helps you with QA, debugging, automated testing, and player-feedback
review. It is built on a simple belief: AI should work *alongside* developers,
not replace them. Spiced suggests, explains, and helps you reason — you stay in
control of every change to your project.

> **Phase 2** preview: everything from Phases 0–1 (desktop skeleton, local
> storage, AI provider boundary, and the **Unity Debugging Buddy**) plus the
> **Automated Testing** foundation — manual test cases and AI-assisted review of
> test results you gathered. Feedback Review remains an honest placeholder.

---

## Ethical purpose

Spiced is deliberately *not* marketed as a magical, autonomous replacement for
developers. Its design principles:

- **You stay in control.** Spiced never modifies your project files on its own.
  In this phase it performs no automatic file modification and runs no engine
  commands.
- **Local first.** Projects, usage, and settings live in a local SQLite database
  on your machine. Nothing is uploaded.
- **Explicit sharing.** Your project files are never sent to an AI provider
  without a future, explicit confirmation step. The built-in connection test
  sends only a short, fixed message — never your files.
- **Honest voice.** Spiced speaks like a calm, professional teammate, not a hype
  machine.

## Unity Debugging Buddy (Phase 1)

The first real feature helps you understand Unity errors faster — without ever
taking control of your project.

**Connect a Unity project**

1. Open **Projects** and create (or select) a project.
2. It becomes the *active* project automatically; click **Choose Unity Folder…**
3. Spiced checks the folder for `Assets/` and `ProjectSettings/`. Valid projects
   are marked; anything else gets a friendly warning (the path is still saved).
   The right-hand context panel shows the active project and its Unity status.

**Analyze a log**

1. Open **Debugging Buddy**.
2. Paste a Unity console error, or **Import log file…** (`.log` / `.txt`).
3. Click **Analyze**. Spiced parses the log locally to find the error type,
   affected script, and line, then asks your selected provider for calm,
   structured guidance: *likely issue · evidence · what to check in Unity ·
   safe next steps · what not to change yet*.
4. Each analysis is saved as a debug session under the active project and shown
   in **Recent sessions**.

Only a small, relevant excerpt of the log is ever sent to a provider — never the
full log and never your project files. Try it with the **mock** provider first;
it works offline with no API key.

## Automated Testing (Phase 2)

The Automated Testing screen has two halves. The first works completely offline,
with no AI provider at all; the second asks your selected provider to interpret
results *you* gathered. Spiced never runs your tests and never touches your
Unity project.

**Author manual test cases**

1. Pick an active project on **Projects**, then open **Automated Testing**.
2. Fill in a title and choose a **category** (Gameplay, UI, Controls,
   Progression, Save/Load, Performance, Build Readiness, Accessibility, General)
   and a **priority** (Low, Medium, High, Critical). Add optional steps and an
   expected result, then click **Add test case**.
3. Track each case with a **status** — Not Run, Pass, Fail, or Blocked. When you
   mark a case **Fail**, you can attach a short failure note. This all works with
   no API key.
4. Select a case in the list to load it into the form. Change any field and click
   **Save changes**, or click **Delete** (with confirmation) to remove it — your
   saved test-run history is never affected. Use **New / clear** to go back to
   authoring a fresh case.

**Review test results**

1. Paste your test-run output, or **Import result file…** (`.txt`, `.log`,
   `.json`, or `.xml`, including NUnit-style XML).
2. Spiced parses it locally into pass/fail/skipped counts, failure names, a
   trimmed excerpt, and a parser-confidence level (low/medium/high).
3. Click **Analyze**. Your selected provider returns a calm, structured review:
   *result summary · main quality risks · failures to inspect · a retest
   checklist · what it will not assume yet*. It never claims to have run the
   tests and never proposes automatic changes.
4. Each analysis is saved as a compact test run under the active project and
   shown in **Recent test runs** — only the excerpt and summaries are stored,
   never the full output.

As with debugging, only the parsed summary and a trimmed excerpt are sent to a
provider. Use the **mock** provider to try it offline with no key.

## Current MVP scope (Phases 0–2)

- Python + PySide6 desktop application (normal resizable window).
- Three-region layout: left sidebar navigation · center chat/workspace · right
  project-context panel.
- Screens: **Projects**, **Debugging Buddy**, **Automated Testing**,
  **Feedback Review**, **Settings**. Feedback Review is a placeholder for a
  later phase.
- Local **SQLite** storage for projects, prompt usage, app settings, debug
  sessions, test cases, and test runs.
- Create and view projects locally, pick an active one, and connect a Unity
  folder with automatic validation.
- **Unity Debugging Buddy**: deterministic local log parsing, structured AI
  guidance, and saved debug-session history (see above).
- **Automated Testing**: offline manual test-case authoring, editing, deletion,
  and status tracking, a deterministic result parser (text/JSON/XML), AI-assisted
  result review, and saved test-run history (see above).
- Local **prompt-usage counter** with mock **Free / Indie / Studio** plan labels
  and a visible remaining-prompt count. *(Plans are UI-only: no billing, no
  accounts, no payment.)*
- Swappable **AI provider boundary** with an **OpenAI** provider (default), a
  **mock** provider (free, offline), and an optional **Gemini** provider.
- A real **connection test** from Settings that calls your selected provider
  when a credential is configured.

### Not in these phases (by design)

- No automatic file modification or code patching.
- No real billing, no cloud accounts.
- No Unity (or other engine) command execution, and no running of Unity tests.
- No sending of project files or full logs to any AI provider — only a trimmed,
  relevant excerpt.
- No deep static analysis of the whole project; Unity folder detection is
  shallow and non-recursive.

## Windows-first notes

The first MVP targets **Windows** with **Unity** projects and **OpenAI** as the
default AI provider (behind the swappable interface above). Gemini remains
available as an optional provider.

- Everything here is cross-platform Python, so it also runs on macOS/Linux for
  development, but Windows is the primary supported target.
- The local database is stored at `%USERPROFILE%\.spiced\spiced.db` on Windows
  (`~/.spiced/spiced.db` elsewhere).
- Use a recent 64-bit Python (3.10+) from python.org. PySide6 ships prebuilt
  wheels for Windows.

## Setup

Requires Python 3.10+.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 2. Install Spiced with its dependencies
pip install -e ".[dev]"
```

### Configure OpenAI (default provider)

The **mock** provider works with no setup and no key — use it for free, offline
testing. To use OpenAI:

1. Get an API key from <https://platform.openai.com/api-keys>.
2. Copy `.env.example` to `.env` and set your key:

   ```
   OPENAI_API_KEY=your-real-key
   ```

   …or export it in your shell:

   ```bash
   # Windows (PowerShell):  $env:OPENAI_API_KEY="your-real-key"
   export OPENAI_API_KEY="your-real-key"
   ```

3. In the app, open **Settings** (OpenAI is selected by default) and click
   **Send test prompt**.

Spiced defaults to the `gpt-4o-mini` model. To use a different one, set
`OPENAI_MODEL` (in `.env` or your shell), e.g. `OPENAI_MODEL=gpt-4o-mini`.

> **Secrets policy:** never hardcode API keys. Keep them in your environment or a
> local `.env` (git-ignored). Do not put keys in commits, logs, docs, or
> screenshots.

### Using Gemini instead (optional)

Gemini is supported but no longer the default. It requires a paid Google API
credential, so it is opt-in:

```bash
pip install -e ".[gemini]"        # installs the optional Gemini dependency
export GEMINI_API_KEY=your-real-key
# optional: export GEMINI_MODEL=gemini-2.0-flash
```

Then choose the **gemini** provider in **Settings**.

### Troubleshooting

- **`OPENAI_API_KEY is not set`** — add your key to `.env` or the environment.
- **`The OpenAI model '...' isn't available`** — set `OPENAI_MODEL` to a model
  your key can access (for example `gpt-4o-mini`); available models change over
  time.
- **`OpenAI rejected the API key`** — double-check `OPENAI_API_KEY` for typos or
  a revoked/expired key.
- **Gemini `model ... is not found / not supported`** — set `GEMINI_MODEL` to a
  supported model and confirm you installed the `[gemini]` extra.

## Run

```bash
python -m spiced.app.main
```

(After `pip install`, the `spiced` GUI script is also available.)

## Develop

```bash
pytest          # run tests
ruff check .    # lint
```

## Project layout

```
src/spiced/
├── app/          # entry point + composition root (services wiring)
├── ui/           # PySide6 window, panels, theme, and screens
├── core/         # usage counter, project/debugging/testing use-cases, log + result parsers
├── ai/           # provider interface, OpenAI (default), mock, Gemini, prompt templates
├── storage/      # SQLite database + repositories (projects, sessions, test cases/runs, settings, usage)
└── connectors/   # Unity project-folder detection (shallow, read-only)
```

## License

[MIT](LICENSE)
