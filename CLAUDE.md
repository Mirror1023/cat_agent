# CatGram Agent — Claude Working Rules

## Project Overview

CatGram is a Flask-based Instagram automation agent that publishes cat content (images and Reels) to Instagram, replies to comments, and runs an engagement loop. It is a single-developer production app — mistakes cost real Instagram API calls and real posts.

**Stack:** Python 3.11 · Flask · SQLAlchemy (SQLite) · APScheduler · Anthropic SDK · Instagram Graph API · Pexels API
**Entry point:** `run.py`
**Dashboard:** http://localhost:5001
**DB:** `data/catgram.db`

### File Map
```
config.py                   — All env vars and app constants (Config class)
run.py                      — Entry point: init DB, start scheduler, start Flask
agent/
  models.py                 — SQLAlchemy models (Post, CommentReply, AgentSettings, ActivityLog, EngagementAction)
  image_sourcer.py          — Fetch images/videos: cat_api, dalle, local, pexels, local_video
  caption_generator.py      — Claude-powered caption + hashtag generation; vision scoring
  instagram_client.py       — Instagram Graph API client (publish_post, publish_reel, comments, likes)
  scheduler.py              — APScheduler: auto_post, manual_post, check_comments, run_engagement
  comment_responder.py      — Fetches and replies to new comments
  engagement_agent.py       — Likes and comments on hashtag posts
web/
  app.py                    — Flask app factory (create_app)
  auth.py                   — Session-based admin auth
  routes.py                 — All HTTP routes: dashboard, compose, preview, settings, logs
  templates/                — Jinja2 HTML templates (base.html, dashboard, compose, etc.)
images/
  local/                    — Drop .jpg/.png/.webp images or .mp4/.mov videos here
  history/                  — Auto-saved copies of posted images/videos
data/
  catgram.db                — SQLite database
tasks/
  lessons.md                — Self-improvement log: mistakes made and rules to prevent them
```

---

## Workflow Orchestration

### 1. Plan Before Building
- Enter plan mode for ANY non-trivial task (3+ steps, touches multiple files, or has architectural impact)
- Write out the affected files and what changes before touching anything
- If something goes sideways mid-task, STOP and re-plan — don't patch forward blindly
- For bugs: diagnose fully before writing a single line of fix

### 2. Subagent Strategy
- Use subagents for: code reviews, parallel test runs, deep codebase exploration, research
- Keep the main context window clean — offload exploration to Explore agents
- Spawn agents in parallel when tasks are independent
- One focused task per subagent — don't ask a subagent to do everything

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with what went wrong and the rule to prevent it
- Format: `## [date] — [short title]` / `**Mistake:**` / `**Rule:**`
- Review `tasks/lessons.md` at the start of each session for relevant patterns
- The goal is a mistake rate that approaches zero over time

### 4. Verification Before Done
- Never say a task is complete without proving it works
- For Python changes: run an import or smoke test before declaring done
- For UI changes: restart the app (Flask non-debug mode caches templates)
- For DB changes: verify columns exist via `inspect(engine).get_columns("posts")`
- Ask: "Would this survive a code review?"

### 5. Demand Elegance
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky, implement the clean solution instead
- Skip for simple, obvious one-liners — don't over-engineer
- Don't add abstractions for hypothetical future requirements

### 6. Autonomous Bug Fixing
- When given a bug or error: read the traceback, find the root cause, fix it
- Don't ask the user to check logs you can read yourself
- Don't suggest — implement. Don't explain what you'd do — do it.

---

## Task Management

1. **Plan First** — for multi-step tasks, outline files and changes before starting
2. **Verify Plan** — confirm approach makes sense before implementing
3. **Track Progress** — use TaskCreate/TaskUpdate for complex multi-file work
4. **Explain Changes** — give a concise summary of what changed and why after each step
5. **Verify Results** — run a smoke test or check output before marking done
6. **Capture Lessons** — after any user correction, update `tasks/lessons.md`

---

## Core Principles

- **Simplicity First** — make every change as small as possible. Touch only what's needed.
- **No Laziness** — find root causes. No temporary hacks. No `# TODO: fix later`.
- **Minimal Impact** — a bug fix doesn't need surrounding refactors. Stay focused.
- **Security Minded** — this app calls real APIs and serves a web UI. Never trust user input, always validate paths, never expose secrets.
- **No Silent Failures** — every error path must log via `log_activity()`. Never swallow exceptions silently.
- **Real API Awareness** — Instagram API calls cost rate-limit quota. Pexels API has rate limits. Don't make unnecessary calls during development.

---

## Project-Specific Patterns

### Adding a new image/video source
1. Add method `_from_<source>(used_urls)` to `ImageSourcer`
2. Add candidates method `_<source>_candidates(used_urls)`
3. Add to `get_image()` and `get_image_candidates()` dispatch
4. Only add to `random` pool if it doesn't require `upload_to_hosting()` (local files do — skip random for those)
5. Include `media_type: "image"|"video"` in returned dict
6. Add `thumbnail_url` for video sources so Claude vision can analyze them

### Publishing a post
- Images: `ig.publish_post(image_url, caption)` → creates container → polls → publishes
- Reels: `ig.publish_reel(video_url, caption)` → same flow but `max_wait=300s`
- Always validate URL reachability before hitting the API
- `save_to_history()` is called after every successful publish — stream large files

### DB changes
- Add column to `Post` model in `models.py`
- Add idempotent `ALTER TABLE` migration in `init_db()` using `sqlalchemy.inspect`
- Add new field to `Post.to_dict()` — never leave it out
- Restart app after schema changes

### Flask templates
- Running in non-debug mode (`debug=False`) — **Jinja2 caches templates**
- Always restart the app after any template change
- All routes are in `web/routes.py` registered via `register_routes(app)`
- Flash messages use categories: `"success"`, `"error"`, `"info"`

### Caption generation
- `generate_caption(context, image_url, is_video)` — pass `is_video=True` for Reels
- For Pexels videos: pass `thumbnail_url` as `image_url` so Claude can see a frame
- For local videos: no thumbnail available — text-only generation
- `select_best_image()` skips vision scoring for video and LOCAL: candidates

### Settings / configuration
- Runtime settings live in `agent_settings` DB table, accessed via `get_setting()` / `set_setting()`
- Static config (API keys, paths) lives in `config.py` / `.env`
- Never hardcode API keys — always read from `Config`

---

## Common Gotchas

- **Template not updating?** Restart the app — non-debug Flask caches Jinja2 templates
- **DB column missing?** Run `init_db()` — the migration is idempotent
- **Pexels HEAD request 405?** Normal — CDN doesn't support HEAD, falls back to streaming GET
- **local_video in random pool?** Don't — `upload_to_hosting()` raises `NotImplementedError`
- **`media_type` missing from dict?** Always add new Post columns to `to_dict()`
- **Instagram container timeout?** Reels need up to 300s, images only 60s
- **`save_to_history` for large videos?** Uses streaming chunks — don't switch to `.content`
