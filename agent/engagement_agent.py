"""
Engagement agent — finds, likes, and occasionally comments on quality cat posts.

Flow per cycle:
1. Pick a random set of cat hashtags from settings
2. Fetch recent IMAGE posts for each via the Hashtag Search API
3. Filter out posts already seen in the DB
4. Score each image with Claude vision (is it a cat? quality 1-10?)
5. Like the top-scoring posts up to the per-cycle limit
6. On ~35% of liked posts, generate and post a short natural comment
7. Respect hard hourly caps and randomised pacing to avoid bot patterns

Requires:
  - instagram_manage_likes permission (for liking)
  - instagram_business_manage_comments permission (for commenting)
"""

import json
import random
import time

import anthropic

from config import Config
from agent.models import Session, EngagementAction, log_activity, get_setting
from agent.instagram_client import InstagramClient

_MAX_LIKES_PER_HOUR = 30
_MAX_COMMENTS_PER_HOUR = 10
_MIN_SCORE = 6              # Posts scoring below this are skipped
_COMMENT_PROBABILITY = 0.35  # ~1 in 3 liked posts gets a comment
_LIKE_PAUSE = (8, 22)       # Seconds between likes
_COMMENT_PAUSE = (10, 30)   # Seconds between like and comment on same post


class EngagementAgent:
    def __init__(self):
        self.ig = InstagramClient()
        self.claude = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_hashtags(self) -> list:
        raw = get_setting("engagement_hashtags", "cats,catsofinstagram,catlovers,kittens,catlife")
        return [h.strip().lstrip("#") for h in raw.split(",") if h.strip()]

    def _likes_this_hour(self, session) -> int:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        return (
            session.query(EngagementAction)
            .filter(EngagementAction.action == "like")
            .filter(EngagementAction.created_at >= cutoff)
            .count()
        )

    def _comments_this_hour(self, session) -> int:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        return (
            session.query(EngagementAction)
            .filter(EngagementAction.comment_text.isnot(None))
            .filter(EngagementAction.created_at >= cutoff)
            .count()
        )

    def _already_seen(self, media_id: str, session) -> bool:
        return (
            session.query(EngagementAction)
            .filter_by(instagram_media_id=media_id)
            .first()
        ) is not None

    def _score_post(self, media_url: str) -> dict:
        """Use Claude vision (Haiku) to score a post. Returns score, is_cat, reason."""
        try:
            response = self.claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "url", "url": media_url}},
                        {"type": "text", "text": (
                            "Is there a cat in this photo? Score it 1-10 for Instagram engagement "
                            "(cuteness, image quality, originality). Penalise spam, reposts, poor quality. "
                            'Reply JSON only: {"is_cat": true, "score": 8, "reason": "fluffy orange tabby in sunlight"}'
                        )},
                    ],
                }],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as e:
            log_activity("engagement_score_error", str(e), level="warning")
            return {"is_cat": True, "score": 5, "reason": "vision unavailable"}

    def _generate_comment(self, media_url: str) -> str:
        """
        Generate a short, natural comment based on the actual image.
        Varies in style — sometimes just emoji, sometimes a few words,
        sometimes a short sentence — to avoid repetitive bot patterns.
        """
        try:
            response = self.claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                system=(
                    "You write short, genuine Instagram comments for a cat lover account. "
                    "RULES: Max 8 words. No hashtags. No 'Cute!' or 'So cute!' — too generic. "
                    "Vary the style: sometimes just 1-2 emojis, sometimes a short reaction, "
                    "sometimes a brief observation about what you see. "
                    "Sound like a real person, not a bot. Never mention our own account. "
                    "Return ONLY the comment text, nothing else."
                ),
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "url", "url": media_url}},
                        {"type": "text", "text": "Write one short comment for this cat photo."},
                    ],
                }],
            )
            return response.content[0].text.strip().strip('"')
        except Exception as e:
            log_activity("engagement_comment_gen_error", str(e), level="warning")
            return None

    def _like_vip_accounts(self, session) -> int:
        """Like all recent unseen posts from VIP accounts. Always likes — no scoring needed."""
        raw = get_setting("vip_accounts", "")
        usernames = [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]
        if not usernames:
            return 0

        liked = 0
        for username in usernames:
            try:
                media_list = self.ig.get_user_media_by_username(username)
                for media in media_list:
                    if media.get("media_type") != "IMAGE":
                        continue
                    if self._already_seen(media["id"], session):
                        continue

                    media_id = media["id"]
                    action = EngagementAction(
                        instagram_media_id=media_id,
                        action="vip_like",
                        hashtag=f"@{username}",
                        score=10,
                    )
                    try:
                        self.ig.like_media(media_id)
                        session.add(action)
                        session.commit()
                        liked += 1
                        log_activity("engagement_vip_liked", f"@{username} — {media_id}", level="success")
                        time.sleep(random.uniform(*_LIKE_PAUSE))
                    except Exception as e:
                        action.action = "skipped"
                        action.skip_reason = f"like_failed: {e}"
                        session.add(action)
                        session.commit()
                        log_activity("engagement_vip_error", f"@{username}: {e}", level="error")
            except Exception as e:
                log_activity("engagement_vip_fetch_error", f"@{username}: {e}", level="warning")

        return liked

    # ── Main cycle ────────────────────────────────────────────────────────────

    def run_engagement_cycle(self) -> dict:
        if get_setting("enable_engagement", "true") != "true":
            return {"liked": 0, "commented": 0, "skipped": 0}

        likes_per_cycle = int(get_setting("likes_per_cycle", "5"))
        session = Session()
        liked = 0
        commented = 0
        skipped = 0

        try:
            # Always process VIP accounts first — they get priority
            vip_liked = self._like_vip_accounts(session)
            liked += vip_liked

            # Check hourly rate limits
            used_likes = self._likes_this_hour(session)
            remaining_likes = _MAX_LIKES_PER_HOUR - used_likes
            if remaining_likes <= 0:
                log_activity(
                    "engagement_rate_limit",
                    f"Hourly like cap reached ({used_likes}/{_MAX_LIKES_PER_HOUR})",
                    level="warning",
                )
                return {"liked": 0, "commented": 0, "skipped": 0}

            used_comments = self._comments_this_hour(session)
            comments_available = _MAX_COMMENTS_PER_HOUR - used_comments

            can_like = min(likes_per_cycle, remaining_likes)
            hashtags = self._get_hashtags()
            random.shuffle(hashtags)

            # Gather candidates
            candidates = []
            for hashtag in hashtags:
                if len(candidates) >= can_like * 4:
                    break
                try:
                    hashtag_id = self.ig.search_hashtag(hashtag)
                    if not hashtag_id:
                        continue
                    media_list = self.ig.get_hashtag_media(hashtag_id)
                    for media in media_list:
                        if (
                            media.get("media_type") == "IMAGE"
                            and media.get("media_url")
                            and not self._already_seen(media["id"], session)
                        ):
                            media["hashtag"] = hashtag
                            candidates.append(media)
                    time.sleep(0.5)
                except Exception as e:
                    log_activity("engagement_hashtag_error", f"#{hashtag}: {e}", level="warning")
                    continue

            if not candidates:
                log_activity("engagement_no_candidates", "No fresh candidates this cycle", level="info")
                return {"liked": 0, "commented": 0, "skipped": 0}

            log_activity("engagement_candidates", f"Scoring {len(candidates)} candidates", level="info")

            # Score candidates
            scored = []
            for media in candidates[: can_like * 4]:
                result = self._score_post(media["media_url"])
                media["score"] = result.get("score", 0)
                media["is_cat"] = result.get("is_cat", False)
                media["reason"] = result.get("reason", "")
                scored.append(media)

            scored.sort(key=lambda x: x["score"], reverse=True)

            # Like (and sometimes comment on) top scorers
            for media in scored:
                if liked >= can_like:
                    break

                media_id = media["id"]
                hashtag = media.get("hashtag", "unknown")
                score = media["score"]
                is_cat = media["is_cat"]
                reason = media.get("reason", "")
                media_url = media["media_url"]

                action = EngagementAction(
                    instagram_media_id=media_id,
                    hashtag=hashtag,
                    score=score,
                )

                if not is_cat or score < _MIN_SCORE:
                    action.action = "skipped"
                    action.skip_reason = f"score={score}, is_cat={is_cat}: {reason}"
                    session.add(action)
                    session.commit()
                    skipped += 1
                    continue

                # Like the post
                try:
                    self.ig.like_media(media_id)
                    action.action = "like"
                    session.add(action)
                    session.commit()
                    liked += 1
                    log_activity(
                        "engagement_liked",
                        f"#{hashtag} — score {score}/10 — {reason}",
                        level="success",
                    )
                except Exception as e:
                    action.action = "skipped"
                    action.skip_reason = f"like_failed: {e}"
                    session.add(action)
                    session.commit()
                    skipped += 1
                    log_activity("engagement_like_error", f"{media_id}: {e}", level="error")
                    continue

                # Randomly decide whether to also comment
                should_comment = (
                    comments_available > 0
                    and random.random() < _COMMENT_PROBABILITY
                )

                if should_comment:
                    # Human-like pause between like and comment
                    time.sleep(random.uniform(*_COMMENT_PAUSE))
                    comment_text = self._generate_comment(media_url)
                    if comment_text:
                        try:
                            self.ig.comment_on_media(media_id, comment_text)
                            # Re-query since action may be detached after log_activity()
                            record = session.query(EngagementAction).filter_by(
                                instagram_media_id=media_id
                            ).first()
                            if record:
                                record.comment_text = comment_text
                                session.commit()
                            commented += 1
                            comments_available -= 1
                            log_activity(
                                "engagement_commented",
                                f"#{hashtag} — \"{comment_text}\"",
                                level="success",
                            )
                        except Exception as e:
                            log_activity("engagement_comment_error", f"{media_id}: {e}", level="error")

                # Pause before next like
                time.sleep(random.uniform(*_LIKE_PAUSE))

        except Exception as e:
            log_activity("engagement_cycle_error", str(e), level="error")
        finally:
            Session.remove()

        if liked or skipped:
            log_activity(
                "engagement_cycle_done",
                f"Cycle complete — liked {liked}, commented {commented}, skipped {skipped}",
                level="success" if liked else "info",
            )
        return {"liked": liked, "commented": commented, "skipped": skipped}
