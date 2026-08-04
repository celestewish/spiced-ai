# Spiced

**A human-centered AI companion for indie game developers.**

Spiced helps you with QA, debugging, automated testing, and player-feedback
review. It is built on a simple belief: AI should work *alongside* developers,
not replace them. Spiced suggests, explains, and helps you reason — you stay in
control of every change to your project.

> Everything from Phases 0–6 (desktop skeleton, local storage, AI provider
> boundary, the **Unity Debugging Buddy**, **Automated Testing**, **Feedback
> Review**, the **Project Dashboard**, demo data, onboarding, Regression
> Tracking, Performance & Profiling, Cross-Platform Simulation, Accessibility,
> Version-Aware Suggestions, Code Health, Feedback-to-Task, Community Pulse,
> and opt-in Run Unity Tests) **plus Team & Workflow, Ethics & Transparency,
> and Automation & Pipeline** (Phases A–F): real multi-user **Small-Team
> Mode** on a hosted backend, **Session Summaries**, a **Build Health Score**,
> app-wide **"why am I seeing this?"** source links, **opt-in-only
> telemetry**, an open **Roadmap**, an opt-in **Automated Build Pipeline**,
> **Changelog Generation**, a **Store/Build Checklist**, an **Asset
> Optimization Sweep**, **Dead Reference Detection**, **Naming Consistency**,
> **Dependency & Plugin Update Checks**, **Auto-Generated Unit Tests**, an
> opt-in **Pre-Commit Review** hook, **Economy/Balance Simulation**,
> convention-based **Save/Load Integrity Testing**, **Auto-Generated Dev
> Docs**, **Design Doc Sync**, **Scope-Creep Flagging**, and local-only
> **Crunch-Pattern Awareness**. See [Team & Workflow, Ethics & Automation
> (Phases A–F)](#team--workflow-ethics--automation-phases-af) below for the
> full rundown. Every new feature keeps Spiced's founding rules: nothing is
> sent to AI beyond a trimmed excerpt, and anything that touches your project
> files or launches your engine is opt-in, per project, and never silent.

---

## Ethical purpose

Spiced is deliberately *not* marketed as a magical, autonomous replacement for
developers. Its design principles:

- **You stay in control.** Spiced never modifies your project files or launches
  your engine silently. Every exception is opt-in, per project, and off by
  default: **Run Unity Tests**, the **Automated Build Pipeline** (which also
  writes a standard build script into your project only if none exists, and
  only once the pipeline is enabled), **Auto-Generated Unit Tests** (written
  to disk only after you click **Approve** on a specific file), and the
  **Pre-Commit Review** git hook (which never overwrites a hook it didn't
  create, and always exits 0 — a heads-up, never a blocking gate).
- **Local first, by default.** Solo-Dev Mode is entirely local — projects,
  usage, and settings live in a local SQLite database on your machine, and
  nothing is uploaded. **Small-Team Mode** is the one deliberate exception:
  once you opt in and link a project to a team, that project's shared data
  (session summaries, team membership) flows through a hosted backend so
  teammates can see it — see [Small-Team Mode](#small-team-mode-phase-a--b)
  below. Solo projects are never touched by this.
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

## Testing, Debugging & Feedback expansion (Phase 6)

Nine new features. Deterministic local parsing/scoring always happens first
and works with no AI provider; the AI step only interprets already-correct,
structured evidence. Eight of the nine only ever read numbers and text you
paste or import — Spiced never touches your engine, a profiler, or real
hardware. The one exception is **Run Unity Tests**, and it's opt-in per
project, off by default: everywhere else, "automating tests" means Spiced
helping you review results, never Spiced deciding what to build or replacing
your judgment about what to do with them.

**Regression Tracking** — every debugging session and test-result failure
gets a signature (error type + location, or the failure name) and is checked
against a per-project history of known issues before being recorded. A repeat
match — exact or a close, word-overlap match — surfaces as "resembles an
issue fixed on \<date\>" so you're not re-diagnosing something you already
fixed. Shown as a **Known Issues** panel on **Automated Testing → Functional**
and inline on **Debugging Buddy** analyses, with **Mark resolved**/**Reopen**
controls. Purely local — no AI involved in matching.

**Run Unity Tests** — opt-in per project (a toggle on **Projects**, off by
default), because this is the one place Spiced launches an external process
instead of only reading text you give it. When enabled, **Automated Testing →
Functional** gets a **Run Tests Now** button that launches your project's own
Unity Editor headlessly (`-batchmode -runTests`) for EditMode, PlayMode, or
both. Spiced finds the right Editor version via Unity Hub (matched exactly
against your project's `ProjectVersion.txt` — never a "close enough"
substitute) or a manual path you set; the run is capped at 30 minutes and
always reads Unity's own NUnit-XML results file rather than trusting its exit
code, since Unity's docs say the exit code isn't a reliable pass/fail signal.
From there it's the exact same pipeline as a pasted result: local parsing,
Known Issues matching, and an AI review.

**Performance & Profiling Reports** — paste or import fps/memory/load-time
numbers (plain text like `Waterfall Area: fps=42, memory=850MB, load=3.2s`,
CSV, or JSON) on the new **Automated Testing → Performance** tab. Spiced
flags spikes locally (low fps, a memory jump versus the batch average, long
load times), then asks your provider to phrase them plainly and suggest
plausible (labeled-as-guesses) causes tied to each location.

**Cross-Platform Test Simulation** — an optional **target hardware** picker
on the Performance tab (Low-end PC / Mid-range PC / Handheld) that scales your
measured fps by a documented factor per tier and flags locations that would
likely dip below a playable frame rate. Always labeled as an estimate from
your own numbers, not a real device test.

**Accessibility Pass** — paste a small JSON checklist (HUD element colors,
audio-caption coverage, remappable-controls/text-scaling flags) on
**Automated Testing → Accessibility**. Spiced runs real WCAG contrast math and
a standard simplified colorblind-simulation matrix locally, scores the
checklist out of 100, and asks your provider for specific fixes — framed as a
prioritized checklist, never a shaming score.

**Version-Aware Suggestions** — paste a C# script into the new
**Outdated-API check** section on **Debugging Buddy**. **Scan** runs fully
offline and free against a small, curated table of Unity APIs Unity itself has
marked obsolete (e.g. `WWW`, `Application.LoadLevel`, `FindObjectOfType`,
`Rigidbody.velocity`), each with its modern replacement and a one-line
rationale. **Analyze with AI** adds narrative framing on top of those exact
hits. This is a curated list, not a live-updated audit of the whole Unity API.

**Code Health Dashboard** — a collapsible **Code Health summary** card on
**Debugging Buddy**. Paste one script and Spiced computes local metrics
(function count/length, a rough branching-complexity count, repeated 4+ line
blocks, TODO/FIXME markers) and asks your provider for a calm, non-judgmental,
prioritized summary — explicitly scoped to the one file pasted in, not a
whole-project static analysis.

**Feedback-to-Task Converter** — the Feedback Review screen now leads with
**theme cards** sorted by frequency (replacing a flat theme list as the
default view), each with a representative example and a **Turn into task**
button. Drafting is a local template, no AI call — the draft is added to a
**Drafted tasks** list where you can **Edit**, **Accept**, **Copy** (to paste
into your own tracker), or **Dismiss** it. Spiced never manages a task board
itself.

**Community Pulse Check-ins** — an opt-in, off-by-default panel at the bottom
of Feedback Review. Enable it and Spiced reads recent messages from exactly
one channel — the free **mock** source by default, or a real **Discord**
channel (read-only, via a bot token) once you set `DISCORD_BOT_TOKEN` and
`DISCORD_CHANNEL_ID` — then asks your provider for a light, high-level
sentiment summary. Always states exactly what channel and how many messages
were read; never reads DMs, never posts or reacts.

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

## Try the demo project (Phase 5A)

Spiced is easier to explore with some data in it. On the **Projects** screen,
click **Load demo project** to seed a small, self-contained sample —
*Starfall Prototype (Demo)* — and make it active. It populates every screen so
the Dashboard has something meaningful to show:

- a Unity validation-style project context (no real folder on disk),
- one debug session (a `NullReferenceException` in `HealthPickup.cs:24`),
- six manual test cases with mixed statuses,
- one test run (5 checks: 2 passed, 2 failed, 1 skipped),
- one player-feedback batch from a six-line playtest scenario.

The demo is deliberately safe: **no Unity is run, no real project files are
touched, and nothing is sent to an AI provider** (its sample analyses are clearly
labelled bundled copy). Loading it is repeat-safe — it never creates a second
demo project and **never reads from or modifies a project you created**. Delete
the demo project any time; your own projects are unaffected.

## Team & Workflow, Ethics & Automation (Phases A–F)

Six phases building out the feature spec's Team & Workflow, Ethics &
Transparency, and Automation & Pipeline sections. Everything here follows the
same rule as Phases 0–6: deterministic local logic does what it can for free
and offline, AI only interprets already-correct evidence, and anything that
writes a file or launches a process is opt-in and never silent.

### Small-Team Mode (Phase A + B)

Spiced is single-user and fully local by default. **Small-Team Mode** is a
real, opt-in exception: a new FastAPI backend (`backend/`), hosted on
Supabase Postgres with Supabase Auth, backs genuine multi-user accounts and
teams — not a local simulation.

- **Sign in / create a team** from the new **Team** section on **Projects**.
  Creating an account or team is never required for solo use.
- **Link a project to a team** to share it. Linking mints a stable
  `project_uuid` for that project so it can be identified across machines.
  Unlinked ("solo") projects are never touched by any of this.
- **Solo-Dev Mode vs. Small-Team Mode** — a toggle in **Settings**. Solo output
  stays exactly as short and prioritized as before (byte-identical prompts).
  Team Mode adds task-assignment *suggestions* and light per-member context to
  the crash-diagnosis, feedback-review, and test-review AI prompts — Spiced
  never assigns work itself, only suggests in its written output.
- **Session Summaries** — a "Summarize / end session" action in the
  right-hand context panel recaps what was tested, fixed, and left open. Saved
  locally always; also posted to the backend (summary text and timestamps
  only — never framed as a wellbeing signal) when the active project is
  team-linked, so teammates can see it.
- **Build Health Score** — a persistent, non-gamified readiness header
  (`Not enough data` / `Needs review` / `Stabilizing` / `Demo candidate`) on
  the **Automated Testing** page, with an expandable "Why?" showing the
  evidence and caveats behind it. Reuses the same cautious assessment logic as
  the Dashboard's readiness label.

### Ethics & Transparency (Phase C)

- **"Why am I seeing this?"** — every AI-result card across Debugging Buddy,
  Automated Testing, and Feedback Review now has an expandable source link
  showing exactly what produced it: the excerpt, matched known issue, test
  case, or feedback cluster. Nothing new is inferred — it surfaces data
  Spiced already stored.
- **Opt-in-only telemetry** — a "Help improve Spiced" toggle in **Settings**,
  off by default, with an exact plain-language list of what's collected if
  enabled: anonymous counts of which features run (a handful of instrumented
  actions), tied to a random per-machine id — never your code, logs, file
  paths, or feedback content, and never linked to your account even if you're
  signed in for Small-Team Mode.
- **Roadmap** — a new sidebar page, separate from the three tool pages. Shows
  a public changelog (seeded from Spiced's real development history) and a
  suggestion board. Viewing needs no account; submitting a suggestion or
  voting uses the same sign-in as Small-Team Mode.

### Automation & Pipeline (Phases D–F)

**Build & release**

- **Automated Build Pipeline** — opt-in per project (**Projects** screen).
  When enabled, Spiced looks for a build-entry-point script in your project
  and writes a standard one (clearly marked as Spiced-generated) only if none
  exists, then triggers headless builds the same way Run Unity Tests does.
  Scheduling is in-app only (a "run nightly while Spiced is open" setting) —
  Spiced does not register anything with Windows Task Scheduler. Only build
  *failures* surface a notification; a quiet, successful build stays quiet.
- **Changelog Generation** — drafts your game's patch notes from `git log`
  plus locally-resolved known issues, on the **Debugging Buddy** page. You
  review and edit before copying it anywhere — Spiced never publishes it.
- **Store / Build Checklist** — a deterministic Steam/itch.io readiness
  checklist reachable from the Build Health Score.
- **Asset Optimization Sweep**, **Dead Reference Detection**, and **Naming
  Consistency Checks** — read-only recursive scans of your `Assets/` folder,
  surfaced on **Debugging Buddy** (the latter two folded into the existing
  Code Health card). Suggestions only; nothing is renamed, deleted, or
  recompressed automatically.

**Code & repo hygiene**

- **Dependency & Plugin Update Checks** — reads `Packages/manifest.json` and
  checks installed versions against the public Unity Package Registry
  (read-only version lookups; no project data is ever sent).
- **Auto-Generated Unit Tests** — point Spiced at a system, review the
  AI-drafted NUnit tests, and click **Approve** per file before anything is
  written to disk. Never overwrites an existing file.
- **Pre-Commit Review** — opt-in per project. Installs a marker-tagged
  `.git/hooks/pre-commit` that flags obvious issues (stray `Debug.Log`s,
  leftover TODOs, merge-conflict markers) — always exits 0, and never
  overwrites a hook it didn't create.
- **Economy/Balance Simulation** — paste economy data (items, costs, currency
  sources) in a documented JSON shape; a local, deterministic simulation
  flags dominant/exploitable strategies on the **Automated Testing** page.
- **Save/Load Integrity Testing** — convention-based: Spiced launches your
  *built game executable* with `SPICED_LOAD_TEST_SAVE_PATH` /
  `SPICED_LOAD_TEST_RESULT_PATH` env vars pointing at a save file and a
  result path; your game is responsible for attempting the load and writing
  back `{"success": bool, "error": str|null}`. Full contract in
  [`docs/save_load_integrity_hook.md`](docs/save_load_integrity_hook.md).
  Only works for games that add this hook.

**Documentation & dev wellbeing**

- **Auto-Generated Dev Docs** — scans your `.cs` scripts for classes, public
  methods, and doc comments, and asks the AI for a living plain-language
  summary. Versioned snapshots, regenerated on request (no background file
  watcher) — a **Docs** section on **Debugging Buddy**.
- **Design Doc Sync** — opt-in per project. Upload or paste your *own game's*
  design doc (not Spiced's), and Spiced compares it against the latest Dev
  Docs snapshot to flag drift either direction.
- **Scope-Creep Flagging** — built on the same snapshot history, gently flags
  when the codebase keeps growing in ways the design doc doesn't mention.
  Paired with Design Doc Sync on the same page.
- **Crunch-Pattern Awareness** — purely local, computed from your own session
  summary timestamps. If a sustained pattern of late-night or very long
  sessions shows up over the trailing week, a quiet, dismissible note appears
  in the right-hand context panel: *"You've logged N late or long work
  session(s) in the last 7 days."* No judgment, no action taken, and this
  data is never sent anywhere — not even to the team backend for a
  team-linked project.

## Current MVP scope (Phases 0–6)

- Python + PySide6 desktop application (normal resizable window).
- Three-region layout: left sidebar navigation · center chat/workspace · right
  project-context panel.
- Screens: **Dashboard**, **Projects**, **Debugging Buddy**, **Automated
  Testing**, **Feedback Review**, **Roadmap**, **Settings**.
- Local **SQLite** storage for projects, prompt usage, app settings, debug
  sessions, test cases/runs, feedback batches/tasks, known issues, performance/
  accessibility/version-check/code-health reports, community check-ins,
  session summaries, build/asset-scan/dependency-check/changelog/economy-sim/
  save-integrity reports, generated test drafts, and dev-docs/design-doc-sync
  snapshots.
- Optional **hosted backend** (`backend/`, FastAPI + Supabase Postgres +
  Supabase Auth) powering Small-Team Mode, telemetry, and the Roadmap — never
  required for solo use (see [Team & Workflow, Ethics & Automation
  (Phases A–F)](#team--workflow-ethics--automation-phases-af)).
- Create and view projects locally, pick an active one, and connect a Unity
  folder with automatic validation.
- **Unity Debugging Buddy**: deterministic local log parsing, structured AI
  guidance, saved debug-session history, an outdated-API scanner
  (Version-Aware Suggestions), and a collapsible Code Health card (see above).
- **Automated Testing**: offline manual test-case authoring/editing/deletion
  and status tracking; a deterministic functional result parser (text/JSON/
  XML) with AI-assisted review; opt-in **Run Unity Tests** (a real, headless
  Unity Test Runner invocation feeding the same parser); a **Performance**
  tab (fps/memory/load-time parsing, spike detection, and an optional
  target-hardware simulation); an **Accessibility** tab (WCAG contrast +
  colorblind-simulation checklist); and a cross-feature **Known Issues**
  panel (Regression Tracking) (see above).
- **Feedback Review**: a deterministic feedback parser (text/Markdown/CSV/
  JSON), offline heuristic classification shown as frequency-sorted theme
  cards, AI-assisted review that separates bugs from design preferences, a
  local Feedback-to-Task Converter, saved feedback-batch history, and an
  opt-in, off-by-default Community Pulse Check-in panel (see above).
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

- **No automatic file modification without an explicit, opt-in gate.** Every
  place Spiced writes to your project is either a per-project toggle you turn
  on (Build Pipeline's build script, the Pre-Commit hook) or a specific
  per-file **Approve** click (Auto-Generated Unit Tests). Nothing is written
  silently, and Spiced never overwrites a file or hook it didn't create.
- **No real billing, and no cloud account is ever required.** Solo-Dev Mode
  needs no account at all. Small-Team Mode is the one deliberate exception —
  real accounts via Supabase Auth, entirely opt-in, only for teams that choose
  to link a project — and there is still no billing anywhere in the app.
- No Unity (or other engine) command execution and no real profiler/hardware
  access beyond a short, deliberate, always-opt-in list: **Run Unity Tests**,
  the **Automated Build Pipeline**, and **Save/Load Integrity Testing** (which
  launches your *built game*, not the Editor, and only if your game
  implements the documented hook). Performance, Cross-Platform Simulation,
  Accessibility, Version-Aware Suggestions, Economy Simulation, and the
  original Code Health metrics still work only from numbers/code you paste or
  import, never from live engine introspection.
- No sending of project files or full logs to any AI provider — only a trimmed,
  relevant excerpt. Small-Team Mode's backend sync follows the same rule:
  session summaries send only AI-produced summary text and timestamps, never
  raw files, code, or feedback content.
- No deep static analysis beyond specific, narrow, read-only scans: Dead
  Reference Detection, the Asset Optimization Sweep, Naming Consistency, and
  Auto-Generated Dev Docs each walk `Assets/` for one specific, documented
  purpose — none of them modify anything, and Unity folder *detection* itself
  (`connectors/unity.py`) stays shallow and non-recursive. Code Health /
  Version-Aware Suggestions on a single pasted file are unchanged.
- No scraping of external platforms beyond the same two narrow, opt-in
  exceptions as before: Community Pulse Check-ins (one read-only Discord
  channel) and the new Dependency & Plugin Update Checks (read-only public
  package-version lookups against the Unity Package Registry — no project
  data is ever sent). No posting to GitHub or other external services.
- Spiced never decides your game's design; it organizes feedback and suggests,
  and you decide what to act on. Scope-Creep Flagging and Crunch-Pattern
  Awareness are the same in spirit — informational nudges, never a gate or a
  score, and Crunch-Pattern data never leaves your machine even in
  Small-Team Mode.
- The Project Dashboard and Build Health Score are deterministic and offline:
  they send nothing to any AI provider, keep no build snapshots beyond what
  you explicitly ran through the Build Pipeline, and never mark a project as
  definitively ready to ship — every readiness label is a planning aid, not a
  verdict.

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

### Enabling Small-Team Mode (optional)

Not required for solo use. To try real multi-user Team Mode, you need the
backend running and the desktop app pointed at it:

```bash
# 1. Set up the backend (separate Python project — see backend/README.md)
cd backend
python -m venv .venv && .venv\Scripts\activate   # or source .venv/bin/activate
pip install -e .
copy .env.example .env    # fill in SUPABASE_URL, SUPABASE_ANON_KEY,
                           # SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload

# 2. Point the desktop app at Supabase + your backend (repo root .env or shell env)
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SPICED_BACKEND_URL=http://127.0.0.1:8000   # defaults to this if unset
```

Then in the app: **Settings → Small-Team Mode** to switch on, sign up/in when
prompted, create or join a team on **Projects**, and link a project to it.
Solo projects and Solo-Dev Mode are completely unaffected if you never do
this.

### Using Gemini instead (optional)

Gemini is supported but no longer the default. It requires a paid Google API
credential, so it is opt-in:

```bash
pip install -e ".[gemini]"        # installs the optional Gemini dependency
export GEMINI_API_KEY=your-real-key
# optional: export GEMINI_MODEL=gemini-2.0-flash
```

Then choose the **gemini** provider in **Settings**.

### Connecting Discord for Community Pulse (optional)

Community Pulse Check-ins default to a free, offline mock source and stay
off until you enable them on the **Feedback Review** screen. To read a real
channel instead:

1. Create a Discord bot and invite it to your server with permission to view
   the channel and read message history (no other permissions are needed —
   Spiced never posts or reacts).
2. Add its token and the target channel's ID to `.env` (uses the same
   never-commit secrets policy as the AI provider keys):

   ```
   DISCORD_BOT_TOKEN=your-bot-token
   DISCORD_CHANNEL_ID=your-channel-id
   ```

3. In **Feedback Review**, check **Enable Community Pulse (opt-in)** and set
   the source to **discord**.

Uses only Python's standard library (`urllib`) for the API call — no extra
dependency to install.

### Enabling Run Unity Tests (optional)

Off by default, per project. To let Spiced launch your project's own Unity
Editor to run its tests:

1. Connect a valid Unity folder for the project first (**Projects** screen) —
   Spiced reads the required Editor version from its `ProjectVersion.txt`.
2. Install that exact Unity version via Unity Hub. Spiced looks it up with
   Unity Hub's own `editors -i` command and will not substitute a "close
   enough" version, since opening a project with the wrong Editor can trigger
   an unwanted upgrade/reimport.
3. On **Projects**, check **"Allow Spiced to run this project's Unity
   tests."** If Hub isn't installed, or you want to pin a specific Editor
   copy, set its `Unity.exe` path directly in the override field instead.
4. On **Automated Testing → Functional**, pick EditMode / PlayMode / Both and
   click **Run Tests Now**. Runs are capped at 30 minutes (a slow first-time
   asset import is the usual reason a run takes a while) and always read
   Unity's own results XML rather than trusting its exit code.

### Troubleshooting

- **`OPENAI_API_KEY is not set`** — add your key to `.env` or the environment.
- **`The OpenAI model '...' isn't available`** — set `OPENAI_MODEL` to a model
  your key can access (for example `gpt-4o-mini`); available models change over
  time.
- **`OpenAI rejected the API key`** — double-check `OPENAI_API_KEY` for typos or
  a revoked/expired key.
- **Gemini `model ... is not found / not supported`** — set `GEMINI_MODEL` to a
  supported model and confirm you installed the `[gemini]` extra.
- **Discord "rejected DISCORD_BOT_TOKEN" / "isn't allowed to read that
  channel"** — double-check the token and confirm the bot was actually added
  to the server with access to that channel.
- **"Unity \<version\> isn't available"** — that exact Editor version isn't
  installed via Unity Hub. Install it, or set a manual `Unity.exe` path on
  the Projects screen.
- **A Unity run times out** — usually a slow first-time asset import, or
  Unity stuck on a dialog batch mode can't dismiss (e.g. license activation).
  Open the project in Unity normally once first to clear both.

## Run

```bash
python -m spiced.app.main
```

(After `pip install`, the `spiced` GUI script is also available.)

For Small-Team Mode, also run the backend (`uvicorn app.main:app --reload`
from `backend/` — see [Enabling Small-Team Mode](#enabling-small-team-mode-optional)
above). Not needed for solo use.

## Develop

```bash
pytest          # run tests
ruff check .    # lint
```

## Project layout

```
src/spiced/
├── app/              # entry point + composition root (services wiring)
├── ui/               # PySide6 window, panels, theme, screens, and reusable widgets
│                     # (source_link/SourceLinkExpander, readiness_badge/ReadinessBadge)
├── core/             # use-cases, parsers, classifiers, and analyzers, plus:
│                     # core/community/ (mock + Discord), session_summary, team_service,
│                     # auth_service, build_pipeline, changelog_draft, release_checklist,
│                     # asset_scan, dependency_check, test_generator, precommit_check/hook,
│                     # economy_simulator, save_load_tester, dev_docs, design_doc_sync,
│                     # scope_creep, crunch_awareness, roadmap_service
├── ai/               # provider interface, OpenAI (default), mock, Gemini, prompt templates
├── storage/          # SQLite database + one repository per table (see database.py's SCHEMA)
├── connectors/       # Unity project-folder detection (shallow, read-only), plus
│                     # unity_build (headless build trigger), unity_scan (Assets/ scanner),
│                     # unity_docs_scan (.cs scanner), unity_package_registry (dependency checks)
└── backend_client/   # HTTP client for the backend + Supabase Auth (config, auth_client,
                      # api_client, telemetry_client) — only used once Small-Team Mode is on

backend/              # separate FastAPI service: Supabase Postgres + Supabase Auth,
                      # teams/session-summaries/telemetry/roadmap. See backend/README.md.
                      # Never required for solo use.
```

## License

[MIT](LICENSE)
