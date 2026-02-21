"""Flask application factory."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask
from config import Config

_NYC = ZoneInfo("America/New_York")

def _nyc_time(dt, fmt="%b %d, %H:%M"):
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_NYC).strftime(fmt)

def create_app(scheduler=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.scheduler = scheduler
    app.jinja_env.filters["nyc_time"] = _nyc_time

    @app.context_processor
    def inject_version():
        return {"app_version": Config.APP_VERSION, "app_version_date": Config.APP_VERSION_DATE}

    from web.routes import register_routes
    register_routes(app)
    return app
