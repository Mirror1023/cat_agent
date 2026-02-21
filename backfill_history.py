"""
One-time script to backfill images/history/ with previously posted images.

Fetches all media from Instagram, cross-references with the local DB,
and downloads any image not already saved in the history folder.

Run from the project root:
    python backfill_history.py
"""

import sys
import requests
from datetime import datetime
from pathlib import Path

# Bootstrap app context so config + models load correctly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config, HISTORY_DIR
from agent.instagram_client import InstagramClient
from agent.models import Session, Post


def already_saved(media_id: str) -> bool:
    """Check if a file containing this media_id already exists in history."""
    return any(media_id in f.name for f in HISTORY_DIR.iterdir() if f.is_file())


def download_image(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"    ✗ Download failed: {e}")
        return False


def main():
    print("CatGram — Image History Backfill")
    print("=" * 40)

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # Load all DB posts that have an Instagram media ID
    db_session = Session()
    try:
        db_posts = (
            db_session.query(Post)
            .filter(Post.status == "posted")
            .filter(Post.instagram_media_id.isnot(None))
            .all()
        )
    finally:
        Session.remove()

    if not db_posts:
        print("No posted records with Instagram media IDs found in the database.")
        return

    print(f"Found {len(db_posts)} posted record(s) in the database.")

    # Fetch all media from Instagram
    print("Fetching media list from Instagram...")
    ig = InstagramClient()
    try:
        ig_media = ig.get_all_media()
    except Exception as e:
        print(f"Failed to fetch Instagram media: {e}")
        sys.exit(1)

    print(f"Instagram returned {len(ig_media)} post(s).")

    # Build lookup: media_id → media_url + timestamp
    ig_lookup = {m["id"]: m for m in ig_media}

    saved = 0
    skipped = 0
    failed = 0
    not_found = 0

    for post in db_posts:
        media_id = post.instagram_media_id

        if already_saved(media_id):
            print(f"  [skip] {media_id} — already in history")
            skipped += 1
            continue

        ig_entry = ig_lookup.get(media_id)
        if not ig_entry:
            print(f"  [miss] {media_id} — not found on Instagram (may be deleted)")
            not_found += 1
            continue

        media_url = ig_entry.get("media_url")
        if not media_url:
            print(f"  [miss] {media_id} — no media_url returned by API")
            not_found += 1
            continue

        # Derive timestamp from Instagram (or fall back to DB created_at)
        raw_ts = ig_entry.get("timestamp") or ""
        try:
            ts = datetime.strptime(raw_ts[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y%m%d_%H%M%S")
        except Exception:
            ts = (post.created_at or datetime.utcnow()).strftime("%Y%m%d_%H%M%S")

        source = post.image_source or "unknown"
        ext = ".jpg"  # Instagram always serves JPEG for photos
        dest = HISTORY_DIR / f"{ts}_{media_id}_{source}{ext}"

        print(f"  [save] {media_id} → {dest.name}")
        if download_image(media_url, dest):
            saved += 1
        else:
            failed += 1

    print()
    print("Done.")
    print(f"  Saved:     {saved}")
    print(f"  Skipped:   {skipped} (already existed)")
    print(f"  Not found: {not_found} (deleted from Instagram or API mismatch)")
    print(f"  Failed:    {failed} (download error)")
    print(f"\nHistory folder: {HISTORY_DIR}")


if __name__ == "__main__":
    main()
