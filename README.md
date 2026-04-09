# 🐱 CatGram Agent

An AI-powered Instagram automation agent that runs a cat-themed account. Uses Claude (Anthropic) for generating captions, hashtags, and comment replies, with multiple configurable image sources.

**Live account:** [instagram.com/catmanduig](https://www.instagram.com/catmanduig/) — 269+ posts, fully automated, running unattended for weeks.

**This version uses the Instagram Platform API with Instagram Login — no Facebook Page required.**

## Features

- **Auto-post cat images** from AI generation (DALL-E), free cat APIs, or your local folder
- **AI-generated captions & hashtags** via Claude (Anthropic)
- **Scheduled posting** — set an interval and walk away
- **Auto-reply to comments** — Claude-powered engagement with your followers
- **Admin Dashboard** — password-protected web UI for managing everything
- **Activity logging** — full audit trail of every action the agent takes
- **Security** — hashed admin password, rate limiting, API key protection

## Architecture

```
cat_agent/
├── run.py                  # Entry point
├── config.py               # Configuration loader
├── .env                    # Your secrets (create from .env.example)
├── agent/
│   ├── instagram_client.py # Instagram Platform API wrapper
│   ├── caption_generator.py# Claude-powered caption/hashtag engine
│   ├── image_sourcer.py    # Multi-source image fetcher
│   ├── comment_responder.py# Auto-reply engine
│   ├── scheduler.py        # APScheduler-based post scheduler
│   └── models.py           # SQLite ORM (SQLAlchemy)
├── web/
│   ├── app.py              # Flask application factory
│   ├── auth.py             # Login/session management
│   ├── routes.py           # Dashboard routes
│   └── templates/          # Jinja2 HTML templates
├── data/                   # SQLite DB lives here
└── images/
    └── local/              # Drop your own cat images here
```

## Prerequisites

1. **Python 3.10+**
2. **An Instagram Business or Creator Account** (no Facebook Page needed!)
3. **A Meta Developer App** with Instagram API (Instagram Login) configured
4. **Anthropic API Key** — get one at https://console.anthropic.com
5. **OpenAI API Key** (optional) — only needed for DALL-E image generation

## Quick Setup

```bash
cd cat_agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your keys
python run.py
```

Open **http://localhost:5000** and log in with your admin password.

## Rate Limits & Safety

- Instagram API: 25 posts per 24 hours (API limit)
- Minimum 1-hour gap between posts enforced
- Comment replies rate-limited to 30/hour
- All actions logged with timestamps
- Admin dashboard requires authentication on every request

## License

MIT — use freely, modify as you like.
