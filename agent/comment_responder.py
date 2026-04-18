"""Auto-reply to new comments on recent posts."""

from datetime import datetime, timezone, timedelta
from agent.instagram_client import InstagramClient
from agent.caption_generator import CaptionGenerator
from agent.models import Session, Post, CommentReply, log_activity, get_setting
from config import Config


class CommentResponder:
    def __init__(self):
        self.ig = InstagramClient()
        self.captioner = CaptionGenerator()

    def process_new_comments(self) -> int:
        if get_setting("enable_comment_replies", "true") != "true":
            return 0

        session = Session()
        replies_sent = 0

        try:
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            recent_replies = session.query(CommentReply).filter(CommentReply.replied_at >= one_hour_ago).count()

            if recent_replies >= Config.MAX_COMMENT_REPLIES_PER_HOUR:
                log_activity("comment_rate_limit", f"Hit rate limit: {recent_replies} replies in last hour", level="warning")
                return 0

            recent_posts = (
                session.query(Post)
                .filter(Post.status == "posted")
                .filter(Post.instagram_media_id.isnot(None))
                .order_by(Post.posted_at.desc())
                .limit(5)
                .all()
            )

            for post in recent_posts:
                if replies_sent >= Config.MAX_COMMENT_REPLIES_PER_HOUR - recent_replies:
                    break
                try:
                    comments = self.ig.get_media_comments(post.instagram_media_id)
                except Exception as e:
                    post_id = post.id
                    err_str = str(e)
                    if "400" in err_str or "404" in err_str:
                        try:
                            post.instagram_media_id = None
                            session.commit()
                            log_activity("comment_fetch_error", f"Post {post_id}: media not found on Instagram, cleared media ID", level="warning")
                        except Exception as fix_err:
                            session.rollback()
                            log_activity("comment_fetch_error", f"Post {post_id}: could not clear media ID: {fix_err}", level="error")
                    else:
                        log_activity("comment_fetch_error", f"Post {post_id}: {e}", level="error")
                    continue

                replied_ids = set(r.instagram_comment_id for r in session.query(CommentReply).filter(CommentReply.post_id == post.id).all())

                for comment in comments:
                    comment_id = comment["id"]
                    if comment_id in replied_ids:
                        continue
                    if replies_sent >= Config.MAX_COMMENT_REPLIES_PER_HOUR - recent_replies:
                        break
                    try:
                        reply_text = self.captioner.generate_comment_reply(comment_text=comment["text"], post_caption=post.caption or "")
                        self.ig.reply_to_comment(comment_id, reply_text)
                        session.add(CommentReply(post_id=post.id, instagram_comment_id=comment_id, original_comment=comment["text"], reply_text=reply_text, status="sent"))
                        session.commit()
                        replies_sent += 1
                        log_activity("comment_replied", f"@{comment.get('username', '?')}: '{comment['text'][:50]}' -> '{reply_text[:50]}'", level="success")
                    except Exception as e:
                        session.add(CommentReply(post_id=post.id, instagram_comment_id=comment_id, original_comment=comment.get("text", ""), reply_text="", status="failed"))
                        session.commit()
                        log_activity("comment_reply_error", f"Comment {comment_id}: {e}", level="error")
        except Exception as e:
            log_activity("comment_process_error", str(e), level="error")
        finally:
            Session.remove()

        return replies_sent
