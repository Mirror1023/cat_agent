"""
Engagement agent — likes comments left on our own posts.

Flow per cycle:
1. Fetch our recent posts (up to 10)
2. For each post, fetch its comments
3. Like any comment not already seen in the DB
4. Respect pacing delays to avoid triggering spam detection

Also attempts VIP account liking and hashtag search if those features
become available in the future (both fail gracefully if permissions
are missing).

Requires:
  - instagram_business_manage_comments (for reading + liking comments)
"""

import random
import time

import anthropic

from config import Config
from agent.models import Session, EngagementAction, log_activity, get_setting
from agent.instagram_client import InstagramClient

_LIKE_PAUSE = (3, 9)    # Seconds between comment likes
_VIP_PAUSE  = (8, 20)   # Seconds between VIP post actions


class EngagementAgent:
    def __init__(self):
        self.ig = InstagramClient()
        self.claude = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _already_seen(self, media_id: str, session) -> bool:
        return (
            session.query(EngagementAction)
            .filter_by(instagram_media_id=media_id)
            .first()
        ) is not None

    def _like_recent_comments(self, session) -> int:
        """Like comments on our recent posts that haven't been liked yet."""
        liked = 0
        try:
            recent_posts = self.ig.get_recent_media(limit=100)
            for post in recent_posts:
                post_id = post["id"]
                try:
                    comments = self.ig.get_media_comments(post_id)
                    for comment in comments:
                        comment_id = comment["id"]
                        username = comment.get("username", "unknown")

                        if self._already_seen(comment_id, session):
                            continue

                        try:
                            self.ig.like_comment(comment_id)
                            action = EngagementAction(
                                instagram_media_id=comment_id,
                                action="comment_like",
                                hashtag=f"post:{post_id}",
                                score=10,
                            )
                            session.add(action)
                            session.commit()
                            liked += 1
                            log_activity(
                                "engagement_comment_liked",
                                f"Liked comment by @{username} on post {post_id}",
                                level="success",
                            )
                            time.sleep(random.uniform(*_LIKE_PAUSE))
                        except Exception as e:
                            # Mark as seen so we don't retry every cycle
                            action = EngagementAction(
                                instagram_media_id=comment_id,
                                action="skipped",
                                hashtag=f"post:{post_id}",
                                skip_reason=str(e),
                            )
                            session.add(action)
                            session.commit()
                            log_activity(
                                "engagement_comment_like_error",
                                f"@{username}: {e}",
                                level="warning",
                            )
                except Exception as e:
                    log_activity(
                        "engagement_comment_fetch_error",
                        f"Post {post_id}: {e}",
                        level="warning",
                    )
        except Exception as e:
            log_activity("engagement_comment_cycle_error", str(e), level="error")
        return liked

    def _generate_vip_comment(self, caption: str, media_url: str = None) -> str:
        """Generate a short, positive, supportive comment based on the post's caption/content."""
        try:
            content = []
            if media_url:
                content.append({"type": "image", "source": {"type": "url", "url": media_url}})
            caption_snippet = (caption or "")[:300]
            content.append({
                "type": "text",
                "text": (
                    f'Write one short supportive comment for this post.'
                    + (f' Caption: "{caption_snippet}"' if caption_snippet else "")
                ),
            })
            response = self.claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                system=(
                    "You write short, genuine Instagram comments. "
                    "RULES: Max 8 words. No hashtags. Be positive and supportive of the post's topic. "
                    "Sound like a real person, not a bot. Return ONLY the comment text, nothing else."
                ),
                messages=[{"role": "user", "content": content}],
            )
            return response.content[0].text.strip().strip('"')
        except Exception as e:
            log_activity("engagement_vip_comment_gen_error", str(e), level="warning")
            return None

    def _like_vip_accounts(self, session) -> int:
        """Like and comment on posts from VIP accounts via Business Discovery API."""
        raw = get_setting("vip_accounts", "")
        usernames = [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]
        if not usernames:
            return 0

        liked = 0
        for username in usernames:
            try:
                media_list = self.ig.get_user_media_by_username(username, limit=100)
                for media in media_list:
                    if media.get("media_type") != "IMAGE":
                        continue
                    if self._already_seen(media["id"], session):
                        continue

                    media_id = media["id"]
                    caption = media.get("caption", "")
                    media_url = media.get("media_url")

                    # Like the post
                    try:
                        self.ig.like_media(media_id)
                        action = EngagementAction(
                            instagram_media_id=media_id,
                            action="vip_like",
                            hashtag=f"@{username}",
                            score=10,
                        )
                        session.add(action)
                        session.commit()
                        liked += 1
                        log_activity(
                            "engagement_vip_liked",
                            f"@{username} — {media_id}",
                            level="success",
                        )
                    except Exception as e:
                        action = EngagementAction(
                            instagram_media_id=media_id,
                            action="skipped",
                            hashtag=f"@{username}",
                            skip_reason=f"like_failed: {e}",
                        )
                        session.add(action)
                        session.commit()
                        log_activity("engagement_vip_like_error", f"@{username}: {e}", level="warning")
                        continue

                    # Comment on the post
                    time.sleep(random.uniform(5, 12))
                    comment_text = self._generate_vip_comment(caption, media_url)
                    if comment_text:
                        try:
                            self.ig.comment_on_media(media_id, comment_text)
                            record = session.query(EngagementAction).filter_by(
                                instagram_media_id=media_id
                            ).first()
                            if record:
                                record.comment_text = comment_text
                                session.commit()
                            log_activity(
                                "engagement_vip_commented",
                                f"@{username} — \"{comment_text}\"",
                                level="success",
                            )
                        except Exception as e:
                            log_activity("engagement_vip_comment_error", f"@{username}: {e}", level="warning")

                    time.sleep(random.uniform(*_VIP_PAUSE))

            except Exception as e:
                log_activity("engagement_vip_fetch_error", f"@{username}: {e}", level="warning")

        return liked

    # ── Main cycle ────────────────────────────────────────────────────────────

    def run_engagement_cycle(self) -> dict:
        if get_setting("enable_engagement", "true") != "true":
            return {"comment_likes": 0, "vip_likes": 0}

        session = Session()
        comment_likes = 0
        vip_likes = 0

        try:
            # Like comments on our own posts
            comment_likes = self._like_recent_comments(session)

            # Like VIP account posts (no-op until business discovery is approved)
            vip_likes = self._like_vip_accounts(session)

        except Exception as e:
            log_activity("engagement_cycle_error", str(e), level="error")
        finally:
            Session.remove()

        if comment_likes or vip_likes:
            log_activity(
                "engagement_cycle_done",
                f"Cycle complete — liked {comment_likes} comments, {vip_likes} VIP posts",
                level="success",
            )
        else:
            log_activity(
                "engagement_run",
                "Cycle complete — nothing new to like",
                level="info",
            )

        return {"comment_likes": comment_likes, "vip_likes": vip_likes}


