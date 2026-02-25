# CatGram — Lessons Learned

Running log of mistakes and the rules that prevent them. Updated after every correction.

---

## 2026-02-22 — Flask template cache requires restart

**Mistake:** Made changes to `dashboard.html` and told the user to just refresh — they couldn't see the changes because Flask in non-debug mode caches Jinja2 templates in memory.

**Rule:** After ANY template change, always restart the app. Never tell the user to "just refresh" without restarting first when `debug=False`.

---

## 2026-02-22 — `media_type` missing from `Post.to_dict()`

**Mistake:** Added `media_type` column to the `Post` model but forgot to include it in `to_dict()`. Every API consumer received `undefined` for that field silently.

**Rule:** Whenever a new column is added to a SQLAlchemy model, immediately add it to `to_dict()` in the same edit. Treat them as a pair.

---

## 2026-02-22 — `local_video` added to `random` pool prematurely

**Mistake:** Added `local_video` to the `random` source pool even though `upload_to_hosting()` raises `NotImplementedError` for all local files. This would cause the auto-scheduler to silently fail every time it randomly selected a local video.

**Rule:** Never add a source to the `random` pool unless it produces a publicly-accessible URL without requiring `upload_to_hosting()`. Pexels videos are safe (already public). Local files are not.

---

## 2026-02-22 — Video caption passed `image_url=None` instead of thumbnail

**Mistake:** For Pexels video candidates, `generate_caption()` was called with `image_url=None`, meaning Claude wrote a generic text-only caption with no visual context — even though Pexels provides a thumbnail frame image for every video.

**Rule:** Always check if a video source provides a `thumbnail_url`. If it does, pass it as `image_url` to `generate_caption()` along with `is_video=True` so Claude can see the content and write an accurate caption.

---

## 2026-02-22 — `validate_for_reel` used content-type denylist instead of allowlist

**Mistake:** The video URL validator only rejected `text/*` content-types, allowing `application/octet-stream`, `application/json`, image URLs, and CDN error pages through unchecked.

**Rule:** URL validators must use allowlists, not denylists. For images: assert `startswith("image/")`. For videos: assert `startswith("video/")`. Reject everything else explicitly.

---

## 2026-02-24 — APP_VERSION_DATE used placeholder time instead of actual time

**Mistake:** When bumping the app version, hardcoded `12:00 PM EST` as the time instead of checking the actual current time.

**Rule:** Always run `date` before writing `APP_VERSION_DATE`. Use the real local time, not a placeholder.

---

## 2026-02-22 — Loading text said "image" for video sources

**Mistake:** The compose page loading spinner said "Selecting best image & writing caption…" even when Pexels or Local Videos was selected as the source.

**Rule:** Any UI copy that references the media type ("image", "photo", "Reel") must be dynamic based on the selected source. Check `['pexels', 'local_video'].includes(source)` and swap the string accordingly.
