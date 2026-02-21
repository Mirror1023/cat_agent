#!/usr/bin/env python3
"""
CatGram Agent — Entry Point
Run this to start the admin dashboard and agent scheduler.

Usage:
    python run.py

Then open http://localhost:5001 in your browser.
(Using port 5001 to avoid macOS Monterey AirPlay conflict on 5000)
"""

import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.models import init_db, log_activity
from agent.scheduler import PostScheduler
from web.app import create_app


def main():
    # Initialize database
    print("🐱 CatGram Agent starting up...")
    init_db()
    log_activity("server_start", "CatGram Agent started", level="info")

    # Create and auto-start scheduler
    scheduler = PostScheduler()
    scheduler.start()

    # Create Flask app
    app = create_app(scheduler=scheduler)

    print("✅ Dashboard ready at http://localhost:5001")
    print("   Log in with your ADMIN_PASSWORD from .env")
    print("   Press Ctrl+C to stop\n")

    # Run Flask (use 5001 to avoid macOS Monterey AirPlay conflict on 5000)
    app.run(host="0.0.0.0", port=5001, debug=False)


if __name__ == "__main__":
    main()
