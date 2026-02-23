"""Dashboard routes for the CatGram Agent admin UI."""

from flask import render_template, request, redirect, url_for, flash, jsonify, send_file, abort
from pathlib import Path
from web.auth import verify_password, login_required, login_user, logout_user
from agent.models import Session, Post, ActivityLog, CommentReply, EngagementAction, log_activity, get_setting, set_setting
from agent.caption_generator import CaptionGenerator
from agent.image_sourcer import ImageSourcer
from agent.instagram_client import InstagramClient


def register_routes(app):

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password = request.form.get("password", "")
            if verify_password(password):
                login_user()
                log_activity("admin_login", "Admin logged in", level="info")
                next_url = request.args.get("next", url_for("dashboard"))
                return redirect(next_url)
            else:
                log_activity("admin_login_failed", "Failed login attempt", level="warning")
                flash("Invalid password", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        session = Session()
        try:
            per_page = 10
            page = int(request.args.get("page", 1))
            from datetime import datetime, timezone, timedelta
            total_posts = session.query(Post).filter(Post.status == "posted").count()
            total_replies = session.query(CommentReply).filter(CommentReply.status == "sent").count()
            failed_posts = session.query(Post).filter(Post.status == "failed").count()
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            failed_24h = session.query(Post).filter(Post.status == "failed").filter(Post.created_at >= since_24h).count()
            total_all = session.query(Post).count()
            recent_posts = session.query(Post).order_by(Post.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
            total_likes_given = session.query(EngagementAction).filter_by(action="like").count()
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            likes_given_today = session.query(EngagementAction).filter(EngagementAction.action == "like").filter(EngagementAction.created_at >= today_start).count()
            scheduler = app.scheduler
            scheduler_status = scheduler.is_running() if scheduler else False
            next_post = scheduler.get_next_run() if scheduler else "N/A"
            ig_info = None
            ig_stats = None
            try:
                ig = InstagramClient()
                ig_info = ig.get_account_insights()
                ig_stats = ig.get_likes_stats()
            except:
                pass
            return render_template("dashboard.html",
                total_posts=total_posts, total_replies=total_replies,
                failed_posts=failed_posts, failed_24h=failed_24h,
                recent_posts=recent_posts,
                scheduler_status=scheduler_status, next_post=next_post,
                ig_info=ig_info, ig_stats=ig_stats,
                total_likes_given=total_likes_given, likes_given_today=likes_given_today,
                page=page, per_page=per_page, total_all=total_all)
        finally:
            Session.remove()

    @app.route("/compose", methods=["GET", "POST"])
    @login_required
    def compose():
        if request.method == "POST":
            image_source = request.form.get("image_source", "cat_api")
            custom_caption = request.form.get("custom_caption", "").strip() or None
            preview_image_url = request.form.get("preview_image_url", "").strip() or None
            preview_image_source = request.form.get("preview_image_source", "").strip() or None
            preview_caption = request.form.get("preview_caption", "").strip() or None
            preview_hashtags = request.form.get("preview_hashtags", "").strip() or None
            _raw_mt = request.form.get("preview_media_type", "").strip()
            preview_media_type = _raw_mt if _raw_mt in ("image", "video") else None
            try:
                scheduler = app.scheduler
                result = scheduler.manual_post(
                    image_source=image_source,
                    custom_caption=custom_caption,
                    preview_image_url=preview_image_url,
                    preview_image_source=preview_image_source,
                    preview_caption=preview_caption,
                    preview_hashtags=preview_hashtags,
                    preview_media_type=preview_media_type,
                )
                flash("Post published successfully!", "success")
                return redirect(url_for("dashboard"))
            except Exception as e:
                flash(f"Post failed: {str(e)}", "error")
        from config import Config as _Config
        sourcer = ImageSourcer()
        local_count = sourcer.get_local_image_count()
        local_video_count = sourcer.get_local_video_count()
        return render_template("compose.html",
            local_count=local_count,
            local_video_count=local_video_count,
            has_openai=bool(app.config.get("OPENAI_API_KEY", "")),
            has_pexels=bool(_Config.PEXELS_API_KEY))

    @app.route("/api/preview-caption", methods=["POST"])
    @login_required
    def preview_caption():
        try:
            captioner = CaptionGenerator()
            result = captioner.generate_caption()
            return jsonify({"success": True, "caption": result["caption"], "hashtags": result["hashtags"]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/schedule", methods=["GET", "POST"])
    @login_required
    def schedule():
        scheduler = app.scheduler
        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "start":
                scheduler.start()
                flash("Scheduler started!", "success")
            elif action == "stop":
                scheduler.stop()
                flash("Scheduler stopped.", "info")
            elif action == "update":
                hours = int(request.form.get("interval_hours", 8))
                max_per_day = int(request.form.get("max_per_day", 3))
                set_setting("post_interval_hours", str(hours))
                set_setting("max_posts_per_day", str(max_per_day))
                scheduler.update_interval(hours)
                flash(f"Schedule updated: every {hours}h, max {max_per_day}/day", "success")
            return redirect(url_for("schedule"))

        return render_template("schedule.html",
            scheduler_running=scheduler.is_running() if scheduler else False,
            next_run=scheduler.get_next_run() if scheduler else "N/A",
            interval_hours=int(get_setting("post_interval_hours", "8")),
            max_per_day=int(get_setting("max_posts_per_day", "3")))

    @app.route("/instructions", methods=["GET", "POST"])
    @login_required
    def instructions():
        if request.method == "POST":
            persona = request.form.get("agent_persona", "")
            custom = request.form.get("custom_instructions", "")
            set_setting("agent_persona", persona)
            set_setting("custom_instructions", custom)
            flash("Instructions saved!", "success")
            return redirect(url_for("instructions"))
        return render_template("instructions.html",
            agent_persona=get_setting("agent_persona", ""),
            custom_instructions=get_setting("custom_instructions", ""))

    @app.route("/logs")
    @login_required
    def logs():
        session = Session()
        try:
            level_filter = request.args.get("level", "all")
            page = int(request.args.get("page", 1))
            per_page = 50
            query = session.query(ActivityLog)
            if level_filter != "all":
                query = query.filter(ActivityLog.level == level_filter)
            total = query.count()
            log_entries = query.order_by(ActivityLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
            return render_template("logs.html",
                logs=log_entries, level_filter=level_filter,
                page=page, total=total, per_page=per_page)
        finally:
            Session.remove()

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "update_source":
                source = request.form.get("image_source", "random")
                set_setting("image_source", source)
                flash(f"Image source set to: {source}", "success")
            elif action == "toggle_replies":
                current = get_setting("enable_comment_replies", "true")
                new_val = "false" if current == "true" else "true"
                set_setting("enable_comment_replies", new_val)
                flash(f"Comment replies {'enabled' if new_val == 'true' else 'disabled'}", "success")
            elif action == "toggle_engagement":
                current = get_setting("enable_engagement", "true")
                new_val = "false" if current == "true" else "true"
                set_setting("enable_engagement", new_val)
                flash(f"Engagement {'enabled' if new_val == 'true' else 'disabled'}", "success")
            elif action == "update_engagement":
                hashtags = request.form.get("engagement_hashtags", "").strip()
                per_cycle = request.form.get("likes_per_cycle", "5").strip()
                set_setting("engagement_hashtags", hashtags)
                set_setting("likes_per_cycle", per_cycle)
                flash("Engagement settings saved", "success")
            elif action == "update_vip":
                raw = request.form.get("vip_accounts", "").strip()
                # Normalise — accept newlines or commas, store as comma-separated
                accounts = [a.strip().lstrip("@") for line in raw.splitlines() for a in line.split(",") if a.strip()]
                set_setting("vip_accounts", ",".join(accounts))
                flash("VIP accounts updated", "success")
            return redirect(url_for("settings"))

        return render_template("settings.html",
            image_source=get_setting("image_source", "random"),
            comment_replies=get_setting("enable_comment_replies", "true") == "true",
            engagement_enabled=get_setting("enable_engagement", "true") == "true",
            engagement_hashtags=get_setting("engagement_hashtags", "cats,catsofinstagram,catlovers,kittens,catlife,meow,kitty,catoftheday"),
            likes_per_cycle=get_setting("likes_per_cycle", "5"),
            vip_accounts=get_setting("vip_accounts", ""))

    @app.route("/api/preview", methods=["POST"])
    @login_required
    def preview():
        data = request.get_json(silent=True) or {}
        source = data.get("image_source", "cat_api")
        try:
            sourcer = ImageSourcer()
            captioner = CaptionGenerator()
            candidates = sourcer.get_image_candidates(source=source)
            image_data = captioner.select_best_image(candidates)
            raw_url = image_data["url"]
            media_type = image_data.get("media_type", "image")
            display_url = raw_url
            if raw_url.startswith("LOCAL:"):
                filename = Path(image_data.get("local_path", "")).name
                display_url = f"/api/local-image?path={filename}"
            is_video = media_type == "video"
            caption_url = image_data.get("thumbnail_url") if is_video else raw_url
            result = captioner.generate_caption(
                context=image_data.get("context"),
                image_url=caption_url or None,
                is_video=is_video,
            )
            return jsonify({
                "success": True,
                "url": display_url,
                "raw_url": raw_url,
                "image_source": image_data["source"],
                "media_type": media_type,
                "caption": result["caption"],
                "hashtags": result["hashtags"],
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/preview-image", methods=["POST"])
    @login_required
    def preview_image():
        data = request.get_json(silent=True) or {}
        source = data.get("image_source", "cat_api")
        try:
            sourcer = ImageSourcer()
            captioner = CaptionGenerator()
            candidates = sourcer.get_image_candidates(source=source)
            image_data = captioner.select_best_image(candidates)
            url = image_data["url"]
            if url.startswith("LOCAL:"):
                filename = Path(image_data.get("local_path", "")).name
                url = f"/api/local-image?path={filename}"
            return jsonify({"success": True, "url": url, "raw_url": image_data["url"], "image_source": image_data["source"]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/local-image")
    @login_required
    def local_image():
        filename = request.args.get("path", "")
        if not filename:
            abort(400)
        # Strip any directory components so only a bare filename is accepted
        filename = Path(filename).name
        if not filename:
            abort(400)
        from config import Config
        base = Path(Config.LOCAL_IMAGES_DIR).resolve()
        image_path = (base / filename).resolve()
        try:
            image_path.relative_to(base)
        except ValueError:
            abort(403)
        # Reject symlinks to prevent escaping the local dir via planted links
        if image_path.is_symlink():
            abort(403)
        if not image_path.exists():
            abort(404)
        return send_file(image_path)

    @app.route("/posts/<int:post_id>/delete", methods=["POST"])
    @login_required
    def delete_post(post_id):
        session = Session()
        try:
            post = session.query(Post).filter_by(id=post_id).first()
            if not post:
                flash("Post not found.", "error")
                return redirect(url_for("dashboard"))
            if post.instagram_media_id:
                try:
                    ig = InstagramClient()
                    ig.delete_post(post.instagram_media_id)
                except Exception as e:
                    log_activity("post_delete_ig_failed", str(e), level="warning")
                    flash(f"Instagram deletion failed — post kept in dashboard: {e}", "error")
                    return redirect(url_for("dashboard"))
            session.delete(post)
            session.commit()
            log_activity("post_deleted", f"Post #{post_id} deleted", level="info")
            flash("Post deleted.", "success")
        except Exception as e:
            flash(f"Delete failed: {str(e)}", "error")
        finally:
            Session.remove()
        return redirect(url_for("dashboard"))

    @app.route("/api/test-connection")
    @login_required
    def test_connection():
        ig = InstagramClient()
        success, message = ig.test_connection()
        return jsonify({"success": success, "message": message})
