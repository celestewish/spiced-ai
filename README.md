# Spiced

**A human-centered AI companion for indie game developers.**

Spiced helps you with QA, debugging, automated testing, and player-feedback
review. It is built on a simple belief: AI should work *alongside* developers,
not replace them. Spiced suggests, explains, and helps you reason — you stay in
control of every change to your project.

> **Phase 4** preview: everything from Phases 0–3 (desktop skeleton, local
> storage, AI provider boundary, the **Unity Debugging Buddy**, the
> **Automated Testing** foundation, and the **Feedback Review** foundation)
> plus the **Project Dashboard** — a calm, offline overview of the active
> project that synthesizes your debugging, testing, and feedback signals into a
> cautious build-readiness label with its evidence and recommended next actions.
> It sends nothing to AI and never claims your game is ready to ship.

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

## Feedback Review (Phase 3)

The Feedback Review screen turns messy player feedback into a calm, structured
read — without ever deciding your game's design for you. Like the other screens,
the local parse works fully offline; only the AI review needs a provider.

**Bring in feedback**

1. Pick an active project on **Projects**, then open **Feedback Review**.
2. Paste playtester comments, or **Import feedback file…** — plain text,
   Markdown notes (`.md`), CSV rows (`.csv`), or a JSON array/object (`.json`)
   with an obvious feedback field.
3. Optionally add a **source label** (e.g. *Playtest 1*, *Discord*, *itch.io
   comments*) so saved batches are easy to tell apart.

**Preview locally, then review with AI**

1. Click **Preview (local only)** to see what Spiced detected with no AI at all:
   the format, entry count, parser confidence, any detected fields, and a
   heuristic category breakdown (bugs, confusion, performance, balance, UI/UX,
   feature requests, praise, and subjective preferences).
2. Click **Analyze** for the full review. Your selected provider returns a
   structured read: *overall summary · recurring themes · potential bugs ·
   confusion points · positive signals · design preferences · prioritized next
   actions · what it will not assume yet*. It separates likely bugs from
   subjective preferences, never treats feedback as objectively correct, and
   leaves the final design judgment with you.
3. Each analysis is saved as a compact feedback batch under the active project
   and shown in **Recent feedback batches** — only a trimmed excerpt, the parsed
   summary, and the analysis outputs are stored, never the full feedback file.

Only the parsed summary, local category counts, and a trimmed excerpt are sent
to a provider — never full feedback files and never your project files. Use the
**mock** provider to try it offline with no key.

## Project Dashboard (Phase 4)

The Dashboard is the first screen you see. It gives the active project a calm,
at-a-glance overview built **entirely from data Spiced already stored** — there
is no AI call and no network here. It refreshes whenever you open it or capture
new debugging, testing, or feedback data.

**What it shows**

1. **Overview** — project name, engine, Unity folder validation status, and path.
2. **Build readiness** — one cautious label with its supporting evidence:
   - *Not enough data* — too little captured to judge.
   - *Needs review* — failing tests, blocked cases, a flagged debug error, or
     likely bug/performance feedback need your attention.
   - *Stabilizing* — tests are passing and only soft signals (e.g. onboarding
     confusion) remain.
   - *Demo candidate* — clean across debugging, testing, and feedback.

   The label is a **planning aid, not a verdict**. Every assessment lists *why*
   and carries an explicit caveat — Spiced never claims your build is ready to
   ship. You stay the decision-maker.
3. **Module cards** — recent debug sessions, test-case/run status, and top
   feedback categories, each with a friendly prompt when a module is still empty.
4. **Recommended next actions** — a suggested, human-approved review queue drawn
   from your failing tests, blocked cases, detected debug errors, and bug or
   confusion feedback. Each item names its source module, a reason, and a
   priority (Low / Medium / High). These are suggestions to help you plan; Spiced
   never acts on them.
5. **Setup reminders** — gentle nudges for any module that has no data yet.

**Project health summary**

Click **Generate summary** for a local, Markdown-friendly recap you can paste
into planning or devlog notes, then **Copy to clipboard**. The summary contains
only counts and short summaries — never full logs, full feedback, test output,
source code, or secrets. Nothing is sent anywhere.

## Current MVP scope (Phases 0–4)

- Python + PySide6 desktop application (normal resizable window).
- Three-region layout: left sidebar navigation · center chat/workspace · right
  project-context panel.
- Screens: **Dashboard**, **Projects**, **Debugging Buddy**, **Automated
  Testing**, **Feedback Review**, **Settings**.
- Local **SQLite** storage for projects, prompt usage, app settings, debug
  sessions, test cases, test runs, and feedback batches.
- Create and view projects locally, pick an active one, and connect a Unity
  folder with automatic validation.
- **Unity Debugging Buddy**: deterministic local log parsing, structured AI
  guidance, and saved debug-session history (see above).
- **Automated Testing**: offline manual test-case authoring, editing, deletion,
  and status tracking, a deterministic result parser (text/JSON/XML), AI-assisted
  result review, and saved test-run history (see above).
- **Feedback Review**: a deterministic feedback parser (text/Markdown/CSV/JSON),
  offline heuristic classification, AI-assisted review that separates bugs from
  design preferences, and saved feedback-batch history (see above).
- **Project Dashboard**: a fully offline, deterministic overview that synthesizes
  debugging, testing, and feedback signals into a cautious build-readiness label
  with evidence, recommended next actions, setup reminders, and a copyable local
  health summary (see above).
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
- No scraping of external platforms or communities, no survey-tool connections,
  and no posting to GitHub or other external services. Feedback comes only from
  what you paste or import.
- Spiced never decides your game's design; it organizes feedback and suggests,
  and you decide what to act on.
- The Project Dashboard is deterministic and offline: it sends nothing to any AI
  provider, keeps no build snapshots, and never marks a project as definitively
  ready to ship — its readiness label is a planning aid, not a verdict.

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
├── core/         # usage counter, project/debugging/testing/feedback/dashboard use-cases, parsers + classifier
├── ai/           # provider interface, OpenAI (default), mock, Gemini, prompt templates
├── storage/      # SQLite database + repositories (projects, sessions, test cases/runs, feedback, settings, usage)
└── connectors/   # Unity project-folder detection (shallow, read-only)
```

## License

[MIT](LICENSE)
