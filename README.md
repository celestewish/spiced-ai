# Spiced

**A human-centered AI companion for indie game developers.**

Spiced helps you with QA, debugging, automated testing, and player-feedback
review. It is built on a simple belief: AI should work *alongside* developers,
not replace them. Spiced suggests, explains, and helps you reason — you stay in
control of every change to your project.

> This is an early **Phase 0** preview: the desktop skeleton, local storage, and
> the AI provider boundary. Most feature screens are honest placeholders for now.

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
  without a future, explicit confirmation step. The built-in Gemini test prompt
  sends only a short, fixed message — never your files.
- **Honest voice.** Spiced speaks like a calm, professional teammate, not a hype
  machine.

## Current MVP scope (Phase 0)

- Python + PySide6 desktop application (normal resizable window).
- Three-region layout: left sidebar navigation · center chat/workspace · right
  project-context panel.
- Screens: **Projects**, **Debugging Buddy**, **Automated Testing**,
  **Feedback Review**, **Settings**. Automated Testing and Feedback Review are
  placeholders for later phases.
- Local **SQLite** storage for projects, prompt usage, and app settings.
- Create and view projects locally.
- Local **prompt-usage counter** with mock **Free / Indie / Studio** plan labels
  and a visible remaining-prompt count. *(Plans are UI-only: no billing, no
  accounts, no payment.)*
- Swappable **AI provider boundary** with a **mock** provider (offline) and a
  **Gemini** provider.
- A real **Gemini test prompt** from Settings when a credential is configured.

### Not in this phase (by design)

- No automatic file modification.
- No real billing, no cloud accounts.
- No Unity (or other engine) command execution.
- No sending of project files to any AI provider.

## Windows-first notes

The first MVP targets **Windows** with **Unity** projects and **Gemini** as the
default AI provider (behind the swappable interface above).

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

### Configure Gemini (optional)

The mock provider works with no setup. To use Gemini:

1. Get an API key from <https://aistudio.google.com/app/apikey>.
2. Copy `.env.example` to `.env` and set your key:

   ```
   GEMINI_API_KEY=your-real-key
   ```

   …or export it in your shell:

   ```bash
   # Windows (PowerShell):  $env:GEMINI_API_KEY="your-real-key"
   export GEMINI_API_KEY="your-real-key"
   ```

3. In the app, open **Settings**, choose the **gemini** provider, and click
   **Send test prompt**.

> **Secrets policy:** never hardcode API keys. Keep them in your environment or a
> local `.env` (git-ignored). Do not put keys in commits, logs, docs, or
> screenshots.

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
├── core/         # plans, usage counter, project use-cases
├── ai/           # provider interface, mock provider, Gemini provider
├── storage/      # SQLite database + repositories
└── connectors/   # placeholder for future engine integrations (Unity first)
```

## License

[MIT](LICENSE)
