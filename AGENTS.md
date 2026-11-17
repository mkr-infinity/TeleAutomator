# TeleAutomator: project instructions for AI contributors

Read this guide before working on any file in this repository. `AGENTS.md` is the single canonical, committed agent guide. Pass it to delegated agents. If a tool does not automatically load it, explicitly attach it as project context. No Markdown file can guarantee that every AI workspace loads it.

## Purpose and architecture

TeleAutomator automates an owner's Telegram account through Telethon/MTProto. An optional Telegram control bot and a mobile Mini App manage the same command engine. Modes are draft, approval, and restricted automatic replies to allowed chats. Python runs the backend; the Mini App uses plain JavaScript, HTML, and CSS. SQLite stores settings, history, approvals, and feedback; separate chat context files retain notes, pins, and memory.

Incoming events → eligibility/privacy checks → per-chat context → prompt/model writer → local style checks → reply scheduling → final authorization/safety checks → Telegram delivery. UI actions must reach the same validated commands as bot controls.

The runtime context worker, reply writer, and local humanizer are stages, not three independent model agents. The humanizer does not require a second model call. Development subagents are separate tools and must not be confused with runtime stages.

## Mandatory working rules

1. **Inspect before editing.** Read the relevant implementation and trace callers, commands, API routes, UI controls, storage, configuration, fixtures, and tests. Identify every affected surface. Use `rg` for searches. Check actual files rather than relying on prior chats or this guide alone.
2. **Ask; never guess missing information.** If anything needed for the task is unclear, missing, or cannot be verified from the repository, ask the user before making the dependent decision or change. This includes requirements, scope, preferences, configuration values, account details, and authorization. Do not silently choose defaults or treat silence as consent. Continue only independent inspection or already-authorized work while waiting. Never invent facts, test results, deployment status, or completed work; distinguish verified evidence from hypotheses.
3. **Use Ponytail and relevant skills.** Read the available Ponytail skill and apply the smallest complete solution, unless the user explicitly turns it off. Read other skills only when useful to the task. If unavailable, say so; do not pretend to have used them. Skills must not override user instructions, skip verification, or create prohibited report artifacts.
4. **Finish the entire authorized scope.** Keep a checklist in the conversation/terminal, update progress as steps finish, and verify affected integrations. After editing each file, reread the diff and reconsider callers and edge cases before moving on.
5. **Keep changes focused.** Reuse existing helpers and dependencies. Avoid speculative abstractions, duplicate controls, unnecessary model calls, and unrelated refactors. Preserve validation, accessibility, error handling, and privacy.
6. **Delegate when useful.** Give development agents explicit scopes, shared constraints, and verification requirements. Avoid concurrent edits to the same files. Review their actual diffs and results; delegation is not evidence of correctness.
7. **Keep secrets private.** Never commit or print credentials, Telegram session strings, private chat contents, or runtime databases. Do not start a live sender, deploy, or send messages merely to run a test.
8. **Reports belong in the terminal/chat only.** Never create audit/report Markdown, JSON, XML, or other report files. Do not add generated test-report artifacts. Source tests and explicitly requested product documentation such as this guide are allowed.
9. **Maintain this guide.** Update the file map and instructions when architecture or workflows change. Current user instructions and higher-priority platform instructions take precedence over this guide. The old ignored lowercase `agent.md`, if present locally, is historical and may be stale; do not use it to override this committed guide or commit it accidentally.

## Git workflow: local commits unless explicitly authorized

For read-only tasks, do not switch branches, pull, stage, commit, or modify files.

Before implementing a new task:

1. Inspect `git status --short`, current branch, recent commits, and remotes. Preserve existing local work; never discard, reset, automatically stash, or rewrite it.
2. With a clean working tree, switch to `main` and run `git pull --ff-only origin main` **before editing**. If network access fails, main diverges, or local edits prevent a safe switch, report the blocker and ask how to proceed; do not silently claim an update succeeded.
3. Create a descriptive new task branch from updated main: `git switch -c fix/<task>` or `docs/<task>`. Never implement directly on main. If this task depends on unmerged local commits, preserve them and use the existing task branch as the new branch's base after updating main; explain the dependency. Ask if the intended base is unclear. Do not drop prior work to force a clean base.
4. Work and commit locally on that branch. For continuation of the same task, stay on its branch; do not switch branches during an unfinished edit. Commit coherent, verified changes as work progresses, using short, specific messages such as `Honor intentional model silence`.
5. Stage explicit intended files, inspect the staged diff, run appropriate checks, commit, then check status and commit contents again. Never include unrelated user changes.
6. **Never push unless the user explicitly authorizes a push or requests a PR that requires publishing the branch. Never create a PR without an explicit PR request.** Permission for one task does not authorize later pushes. The user merges manually; never merge a PR on their behalf.
7. State branch, commit, verification, and whether anything remains uncommitted. Do not equate local commits with a deployed release.

## Behavior to preserve

- Ignore chats outside the explicit allowlist before collecting context or generating replies. Recheck permission and stop/pause state after waits and before delivery.
- When the owner has replied by hand in a chat within `owner_active_minutes` (default 15, 0 disables), automatic replies and reactions there stay quiet; the account's own sent messages never count as manual (`expect_own_send`).
- Keep settings, prompts, context, pins, voice profiles, feedback, and history isolated per chat. Custom settings affect that chat only; otherwise use defaults. Chat overrides must not bypass account-wide safety limits.
- Default global and per-chat cooldown ranges are 5–60 seconds. Verify effective runtime settings, not just environment defaults. Wait for live limits before sending; credit queued/lock waiting toward reading delay while preserving final typing indicators.
- Generate automated conversational replies through the configured model, including rewrites of saved keyword guidance. No canned conversational fallback when a provider is unavailable. Static UI labels and control/status messages are a different category.
- Standalone model `NONE` means intentional silence and must not trigger a fallback reply. Actual empty/malformed responses and request errors can try the next candidate. Preserve usage accounting.
- Stay on the current chat topic, avoid unnecessary replies, respect mention-only and chatty settings, and occasionally join relevant group conversations only when permitted. Do not treat every incoming message as a request for a reply.
- Use only configured personal facts and the configured/synced account persona. Missing facts and identity/automation questions remain silent for the owner; do not fabricate an age, personal history, human denial, or identity explanation.
- Do not emit participant names, usernames, mentions, email addresses, or links in automatic conversational text. Group replies must not quote/tag another user's message. Preserve outgoing filters; prompts alone are not enforcement.
- Capitalize the first alphabetic character of every outgoing automated message bubble without altering the rest unnecessarily. Keep final delivery guards for queued, approved, follow-up, and correction paths.
- Context files live under the configured data directory's `contexts/` folder, separated by chat ID. Preserve user notes and pins when updating model summaries. Filter sensitive content before model calls/storage; handle concurrent writes and allowlist revocation.
- Preserve lifecycle cancellation, duplicate prevention, bounded summary jobs, provider fallback behavior, permission checks, and atomic settings updates.
- Mini App changes must work on mobile, especially Telegram Android: fullscreen/expanded layout where supported, safe-area/keyboard handling, stable popups, swipe behavior, visible errors, and no duplicate actions. Keep startup, polling, payloads, and rendering lightweight.

## Verification and completion

- Use targeted regression tests for behavioral changes, then broader tests when shared safety, storage, transport, or UI flows are affected. Test the failure paths as well as success. For documentation-only changes, verify paths, claims, completeness, and whitespace; do not claim an application test run you did not perform.
- Standard suite: `.venv/bin/python -m pytest tests/ -q`, or `./test.sh -q`. Inspect setup scripts before allowing them to install dependencies. Python 3.10+ is required by project metadata.
- Frontend pytest wrappers run Node and Playwright fixtures. Verify prerequisites and report skips. `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` can select local installations; do not hardcode another developer's filesystem paths.
- Local mocks/browser fixtures are not live Telegram/provider tests or physical Android validation. State those limits. A green suite is not a guarantee that every deployment works.
- Review `git diff --check` and the final diff. Verify changed commands agree across bot, API, and Mini App. Inspect current deployment definitions when deployment behavior changes; do not assume hosted CI exists or ran.
- **Ask before every version bump.** Propose the exact target version and obtain explicit user approval before changing it, unless the user has already explicitly approved that exact version for the current task. Never infer version-bump permission from a request to fix, commit, release, deploy, or create a PR. Without that approval, leave the version unchanged. Once approved, use `python scripts/update_version.py X.Y.Z`; the version source is `app/__init__.py`. The script synchronizes metadata, frontend references, and service-worker caches. Running it without a version also synchronizes files, so it is not a read-only audit command.
- Finish with a short terminal/chat report: what changed; each changed file and purpose; actual checks and outcomes; branch and local commit; blockers/critical risks and untested areas; numbered next improvements with a brief benefit. Never hide a failure or label an unchecked item complete.

## Tracked file map

Paths below are repository-relative. Read actual code before using this map as an implementation specification.

### Project, configuration, and deployment

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Single canonical agent guide, contributor rules, and file map. |
| `README.md` | Project overview, setup, and usage documentation. |
| `REQUIREMENTS.md` | Documented project requirements and behavior. |
| `DEPLOYMENT.md` | Deployment and operational setup guidance. |
| `LICENSE` | Project licensing terms. |
| `CITATION.cff` | Citation metadata and release version. |
| `pyproject.toml` | Python package metadata, dependencies, and pytest configuration. |
| `requirements.txt` | Dependencies used by setup and deployment installs. |
| `.env.example` | Configuration template without live credentials. |
| `.gitignore` | Excludes secrets, sessions, runtime data, and generated files. |
| `.dockerignore` | Excludes unnecessary/private files from Docker build context. |
| `Dockerfile` | Application container build and runtime definition. |
| `compose.yaml` | Local container service, volume, ports, and resource limits. |
| `entrypoint.sh` | Fixes volume ownership as root, drops to UID 10001, and checks storage and session prerequisites. |
| `healthcheck.sh` | Invokes the health-check mode as the unprivileged user. |
| `Procfile` | Hosted process entry point. |
| `railway.json` | Railway build and restart configuration. |
| `render.yaml` | Render service, environment, and health configuration. |
| `run.py` | Cross-platform setup, authentication, tests, and application launcher. |
| `start.sh` | Starts the application using the local virtual environment. |
| `setup.sh` | Unix-like environment/dependency setup. |
| `setup.ps1` | Windows PowerShell setup. |
| `authenticate.sh` | Virtual-environment wrapper for interactive authentication. |
| `session.sh` | Virtual-environment wrapper for session export/generation. |
| `test.sh` | Virtual-environment pytest launcher. |
| `system_prompt.txt` | Base conversational instructions and persona placeholders. |
| `robots.txt` | Root crawler instructions. |
| `sitemap.xml` | Root sitemap metadata. |
| `assets/banner.png` | Project banner image. |
| `assets/logo.png` | Raster project logo. |
| `assets/logo.svg` | Vector project logo. |

### Python application

| File | Purpose |
| --- | --- |
| `app/__init__.py` | Package identity and canonical application version. |
| `app/main.py` | Application startup, service coordination, health mode, and shutdown. |
| `app/config.py` | Environment/CLI configuration parsing and validation. |
| `app/banner.py` | Terminal startup branding. |
| `app/boot_guard.py` | Crash-loop detection and safe-mode recovery. |
| `app/logger.py` | Structured logging and secret redaction. |
| `app/health.py` | Runtime health tracking and status files. |
| `app/session_manager.py` | Local/StringSession loading and secure file handling. |
| `app/telegram_client.py` | Telethon lifecycle, authentication, and account identity. |
| `app/event_handlers.py` | Incoming/outgoing event routing, eligibility, and engagement. |
| `app/message_filter.py` | Message eligibility and account-addressing checks. |
| `app/privacy_manager.py` | Allowlists, exclusions, and privacy controls. |
| `app/notifications.py` | Owner alerts: model errors, quiet-hours notices, and Mini App change-log text. |
| `app/safety_manager.py` | Cooldowns, rate limits, stop/pause, duplicates, and sensitive-content guards. |
| `app/reply_manager.py` | Reply modes, queues, delays, typing, approvals, delivery, and background lifecycle. |
| `app/command_router.py` | Shared command handlers for settings, chats, persona, context, and controls. |
| `app/bot_control.py` | Bot API control channel, menus, callbacks, and command permissions. |
| `app/miniapp_server.py` | Static UI serving, Telegram authentication, JSON endpoints, and action routing. |
| `app/settings_transfer.py` | Validated preference import/export excluding credentials and access grants. |
| `app/ai/__init__.py` | AI package marker. |
| `app/ai/provider.py` | Gemini/OpenAI-compatible providers, candidate fallback, silence, and offline behavior. |
| `app/ai/prompt_manager.py` | Prompt construction, persona rules, cleaning, and outgoing policy checks. |
| `app/ai/reply_generator.py` | Provider selection, reply writing, and local humanization. |
| `app/ai/chat_context.py` | Per-chat snapshots, coalesced persistence, and bounded model summaries. |
| `app/storage/__init__.py` | Storage package marker. |
| `app/storage/database.py` | SQLite settings, history, approvals, feedback, deduplication, and persistence helpers. |

### Mini App and maintenance scripts

| File | Purpose |
| --- | --- |
| `miniapp/index.html` | Dashboard structure, metadata, and asset loading. |
| `miniapp/app.js` | Dashboard state, API calls, Telegram integration, controls, and popups. |
| `miniapp/style.css` | Responsive layout, visual styling, and mobile behavior. |
| `miniapp/sw.js` | Service-worker cache and frontend asset lifecycle. |
| `miniapp/logo.svg` | Dashboard logo. |
| `miniapp/robots.txt` | Mini App crawler instructions. |
| `miniapp/sitemap.xml` | Mini App sitemap metadata. |
| `scripts/authenticate.py` | Interactive Telegram login. |
| `scripts/check_connection.py` | Live account connection/status check; requires credentials. |
| `scripts/generate_session.py` | Session export or creation; output is a secret. |
| `scripts/update_version.py` | Synchronizes release versions and checks for stale references. |

### Tests

| File | Purpose |
| --- | --- |
| `tests/__init__.py` | Test package marker. |
| `tests/conftest.py` | Shared fixtures, including controlled time. |
| `tests/helpers.py` | Shared automation test helpers. |
| `tests/test_ai_prompt.py` | Prompt, cleaning, generation, and provider behavior. |
| `tests/test_background_lifecycle.py` | Worker shutdown, model-only replies, context, and delivery regressions. |
| `tests/test_boot_guard.py` | Crash-loop safe mode and recovery. |
| `tests/test_bot_control.py` | Bot authorization, permissions, callbacks, and controls. |
| `tests/test_bot_menu_engagement.py` | Menu uniqueness, engagement policy, and outgoing context. |
| `tests/test_config.py` | Configuration validation. |
| `tests/test_context_recovery.py` | Context file locking, disk recovery, and oldest-first summary batches. |
| `tests/test_control_atomicity.py` | Atomic access changes, command grants, imports, health readiness, and bounded HTTP reads. |
| `tests/test_cooldown_and_antiflood.py` | Cooldown, typing, serialized delivery, and group anti-flood behavior. |
| `tests/test_deferred_delay_budget.py` | Queue/lock time credited toward reading without skipping typing or Stop. |
| `tests/test_delivery_integrity.py` | Delivery retry guards, stale drafts, chatty parsing, approval batches, and sleep pauses. |
| `tests/test_frontend.py` | Pytest wrappers for Node and browser workflow tests. |
| `tests/test_group_engagement.py` | Open invitations, thread joining, 100% chatty, reaction share, skip logs, pending-reply tolerance, and summary back-off. |
| `tests/test_human_text_policy.py` | Two-line limit, code and instruction guards, and human-text cleaning. |
| `tests/test_launchers.py` | Launcher and container entrypoint behavior (ownership, privilege drop, storage checks). |
| `tests/test_logger.py` | Log redaction. |
| `tests/test_message_filter.py` | Message eligibility. |
| `tests/test_miniapp.py` | Mini App authentication, permissions, API mapping, and HTTP behavior. |
| `tests/test_miniapp_browser.cjs` | Playwright mobile viewport/popup workflows with mocked services. |
| `tests/test_miniapp_frontend.cjs` | JavaScript dashboard workflows with a lightweight DOM fixture. |
| `tests/test_owner_presence.py` | Automation stays quiet for 15 minutes after the owner replies by hand, then resumes. |
| `tests/test_per_chat_context_and_burst.py` | Chat isolation, profiles, context, and burst controls. |
| `tests/test_notifications.py` | Model-error alerts, quiet-hours notices, and Mini App change log. |
| `tests/test_pr_readiness_audit.py` | Regression tests from earlier readiness checks; not an audit report. |
| `tests/test_privacy_manager.py` | Allowlists, blocklists, and exclusions. |
| `tests/test_prompt_integrity.py` | Meaning-safe reply cleaning, length limits, style priority, and summary failures. |
| `tests/test_provider_silence.py` | Intentional NONE versus malformed content and candidate fallback. |
| `tests/test_reply_manager.py` | Core reply orchestration and delivery. |
| `tests/test_reply_policy_and_preferences.py` | Reply policy, history, and preference transfer. |
| `tests/test_reply_stages_and_feedback.py` | Context/writer/humanizer stages, stale drafts, and isolated feedback. |
| `tests/test_reply_timing.py` | Typing inside the cooldown, bubble gaps, reaction matching, pin cache, and identity gate. |
| `tests/test_runtime_recovery.py` | Reconnection, readiness, safe-mode recovery, and session file naming. |
| `tests/test_safety_manager.py` | Safety limits, duplicates, emergency controls, and cooldown persistence. |
| `tests/test_session_manager.py` | Session formats and secure handling. |
| `tests/test_ui_audit_regressions.cjs` | Playwright Mini App regressions for saves, approvals, popups, graph, and swipes. |
| `tests/test_ui_audit_regressions.py` | Pytest wrapper for the UI regression browser script. |
| `tests/test_version_sync.py` | Version propagation and stale asset reference detection. |
| `tests/test_workflow_regressions.py` | Cross-layer authorization, model selection, context, and workflow regressions. |

## Local-only state

`.env`, sessions, SQLite files, context JSON, logs, backups, virtual environments, and local tool configuration are not shared source. Never copy their contents into this guide. Inspect only what a task requires and redact sensitive values. Do not rely on a historical passing-test count, branch name, installed browser path, or deployment image as current evidence; verify each when needed.
