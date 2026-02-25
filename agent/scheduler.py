"""Post scheduler using APScheduler."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.instagram_client import InstagramClient
from agent.caption_generator import CaptionGenerator
from agent.image_sourcer import ImageSourcer
from agent.comment_responder import CommentResponder
from agent.engagement_agent import EngagementAgent
from agent.models import Session, Post, log_activity, get_setting, set_setting, utcnow
from config import Config


class PostScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(daemon=True)
        self.ig = InstagramClient()
        self.captioner = CaptionGenerator()
        self.image_sourcer = ImageSourcer()
        self.comment_responder = CommentResponder()
        self.engagement_agent = EngagementAgent()
        self._running = False

    def start(self):
        if self._running:
            return
        interval_hours = int(get_setting("post_interval_hours", str(Config.POST_INTERVAL_HOURS)))
        self.scheduler.add_job(self.auto_post, trigger=IntervalTrigger(hours=interval_hours), id="auto_post", name="Auto Post Cat Content", replace_existing=True, max_instances=1)
        if get_setting("enable_comment_replies", "true") == "true":
            self.scheduler.add_job(self.check_comments, trigger=IntervalTrigger(minutes=15), id="check_comments", name="Check & Reply to Comments", replace_existing=True, max_instances=1)
        if get_setting("enable_engagement", "true") == "true":
            self.scheduler.add_job(self.run_engagement, trigger=IntervalTrigger(minutes=30), id="engagement", name="Like Cat Posts", replace_existing=True, max_instances=1)
        self.scheduler.add_job(
            self.record_growth_snapshot,
            trigger=IntervalTrigger(hours=24),
            id="growth_snapshot",
            name="Record Follower Growth",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        self._running = True
        set_setting("scheduler_enabled", "true")
        log_activity("scheduler_started", f"Posting every {interval_hours}h", level="success")

    def stop(self):
        if not self._running:
            return
        self.scheduler.shutdown(wait=False)
        self._running = False
        self.scheduler = BackgroundScheduler(daemon=True)
        set_setting("scheduler_enabled", "false")
        log_activity("scheduler_stopped", level="info")

    def is_running(self) -> bool:
        return self._running

    def get_next_run(self) -> str:
        if not self._running:
            return "Scheduler not running"
        job = self.scheduler.get_job("auto_post")
        if job and job.next_run_time:
            return job.next_run_time.astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %-I:%M %p EST")
        return "Unknown"

    def update_interval(self, hours: int):
        set_setting("post_interval_hours", str(hours))
        if self._running:
            self.stop()
            self.start()

    def _get_used_media_urls(self) -> set:
        """Return all image/video URLs that have already been successfully posted."""
        session = Session()
        try:
            rows = session.query(Post.image_url).filter(Post.status == "posted").all()
            return {row[0] for row in rows if row[0]}
        finally:
            Session.remove()

    def _check_rate_limits(self) -> bool:
        session = Session()
        try:
            max_per_day = int(get_setting("max_posts_per_day", str(Config.MAX_POSTS_PER_DAY)))
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            posts_today = session.query(Post).filter(Post.status == "posted").filter(Post.posted_at >= today_start).count()
            if posts_today >= max_per_day:
                log_activity("rate_limit_hit", f"Max posts per day reached ({posts_today}/{max_per_day})", level="warning")
                return False
            last_post = session.query(Post).filter(Post.status == "posted").order_by(Post.posted_at.desc()).first()
            if last_post and last_post.posted_at:
                gap = datetime.now(timezone.utc) - last_post.posted_at.replace(tzinfo=timezone.utc)
                if gap < timedelta(minutes=Config.MIN_POST_GAP_MINUTES):
                    log_activity("rate_limit_gap", f"Too soon since last post ({gap.total_seconds() / 60:.0f}min < {Config.MIN_POST_GAP_MINUTES}min)", level="warning")
                    return False
            return True
        finally:
            Session.remove()

    def _is_video_candidate(self, image_data: dict) -> bool:
        return image_data.get("media_type") == "video"

    def auto_post(self):
        log_activity("auto_post_starting", "Beginning auto-post cycle")
        if not self._check_rate_limits():
            return
        session = Session()
        post = Post(status="draft", created_at=utcnow())
        try:
            used_urls = self._get_used_media_urls()
            candidates = self.image_sourcer.get_image_candidates(used_urls=used_urls)
            image_data = self.captioner.select_best_image(candidates)
            image_url = image_data["url"]
            is_video = self._is_video_candidate(image_data)
            post.image_source = image_data["source"]
            post.image_url = image_url
            post.media_type = "video" if is_video else "image"
            if image_url.startswith("LOCAL:"):
                local_path = image_data.get("local_path", "")
                image_url = self.image_sourcer.upload_to_hosting(local_path)
                post.image_url = image_url
            caption_url = image_data.get("thumbnail_url") if is_video else image_url
            caption_data = self.captioner.generate_caption(context=image_data.get("context"), image_url=caption_url or None, is_video=is_video)
            caption = caption_data["caption"]
            hashtags = caption_data["hashtags"]
            full_caption = f"{caption}\n\n{hashtags}"
            post.caption = caption
            post.hashtags = hashtags
            if is_video:
                media_id = self.ig.publish_reel(image_url, full_caption)
            else:
                media_id = self.ig.publish_post(image_url, full_caption)
            post.instagram_media_id = media_id
            post.status = "posted"
            post.posted_at = utcnow()
            session.add(post)
            session.commit()
            self.image_sourcer.save_to_history(post.image_url, media_id=media_id, source=post.image_source)
            log_activity("auto_post_success", f"Posted: {caption[:80]}... (Media ID: {media_id})", level="success")
        except Exception as e:
            post.status = "failed"
            post.error_message = str(e)
            session.add(post)
            session.commit()
            log_activity("auto_post_failed", str(e), level="error")
        finally:
            Session.remove()

    def manual_post(self, image_source: str = None, custom_caption: str = None,
                    preview_image_url: str = None, preview_image_source: str = None,
                    preview_caption: str = None, preview_hashtags: str = None,
                    preview_media_type: str = None) -> dict:
        session = Session()
        post = Post(status="draft", created_at=utcnow())
        try:
            if preview_image_url:
                image_url = preview_image_url
                post.image_source = preview_image_source or image_source or "unknown"
                post.image_url = image_url
                is_video = preview_media_type == "video"
                if image_url.startswith("LOCAL:"):
                    local_path = image_url[len("LOCAL:"):]
                    image_url = self.image_sourcer.upload_to_hosting(local_path)
                    post.image_url = image_url
                image_context = None
            else:
                used_urls = self._get_used_media_urls()
                candidates = self.image_sourcer.get_image_candidates(source=image_source, used_urls=used_urls)
                image_data = self.captioner.select_best_image(candidates)
                image_url = image_data["url"]
                is_video = self._is_video_candidate(image_data)
                post.image_source = image_data["source"]
                post.image_url = image_url
                if image_url.startswith("LOCAL:"):
                    local_path = image_data.get("local_path", "")
                    image_url = self.image_sourcer.upload_to_hosting(local_path)
                    post.image_url = image_url
                image_context = image_data.get("context")
            post.media_type = "video" if is_video else "image"
            if preview_caption:
                caption = preview_caption
                hashtags = preview_hashtags or ""
            elif custom_caption:
                caption = custom_caption
                hashtags = ""
            else:
                caption_url = image_data.get("thumbnail_url") if is_video else image_url
                caption_data = self.captioner.generate_caption(context=image_context, image_url=caption_url or None, is_video=is_video)
                caption = caption_data["caption"]
                hashtags = caption_data["hashtags"]
            full_caption = f"{caption}\n\n{hashtags}".strip()
            post.caption = caption
            post.hashtags = hashtags
            if is_video:
                media_id = self.ig.publish_reel(image_url, full_caption)
            else:
                media_id = self.ig.publish_post(image_url, full_caption)
            post.instagram_media_id = media_id
            post.status = "posted"
            post.posted_at = utcnow()
            session.add(post)
            session.commit()
            self.image_sourcer.save_to_history(post.image_url, media_id=media_id, source=post.image_source)
            log_activity("manual_post_success", f"Posted: {caption[:80]}...", level="success")
            return post.to_dict()
        except Exception as e:
            post.status = "failed"
            post.error_message = str(e)
            session.add(post)
            session.commit()
            log_activity("manual_post_failed", str(e), level="error")
            raise
        finally:
            Session.remove()

    def check_comments(self):
        try:
            count = self.comment_responder.process_new_comments()
            if count > 0:
                log_activity("comments_processed", f"Replied to {count} comments", level="success")
        except Exception as e:
            log_activity("comment_check_error", str(e), level="error")

    def run_engagement(self):
        try:
            result = self.engagement_agent.run_engagement_cycle()
            log_activity("engagement_run",
                f"Liked {result['comment_likes']} comments, "
                f"{result['vip_likes']} VIP posts, "
                f"{result['commenter_likes']} commenter posts",
                level="info")
        except Exception as e:
            log_activity("engagement_run_error", str(e), level="error")

    def record_growth_snapshot(self):
        try:
            from agent.models import Session, GrowthSnapshot
            info = self.ig.get_account_insights()
            session = Session()
            session.add(GrowthSnapshot(
                followers=info.get("followers_count", 0),
                following=info.get("follows_count", 0),
                posts=info.get("media_count", 0),
            ))
            session.commit()
            Session.remove()
            log_activity("growth_snapshot", f"Recorded: {info.get('followers_count', 0)} followers", level="info")
        except Exception as e:
            log_activity("growth_snapshot_error", str(e), level="warning")
