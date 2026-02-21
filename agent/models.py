from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from config import Config

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, echo=False)
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    instagram_media_id = Column(String(100), nullable=True)
    image_url = Column(Text, nullable=True)
    image_source = Column(String(50))
    caption = Column(Text)
    hashtags = Column(Text)
    status = Column(String(20), default="draft")
    scheduled_at = Column(DateTime, nullable=True)
    posted_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    likes = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "instagram_media_id": self.instagram_media_id,
            "image_url": self.image_url,
            "image_source": self.image_source,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "status": self.status,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "likes": self.likes,
            "comments_count": self.comments_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CommentReply(Base):
    __tablename__ = "comment_replies"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer)
    instagram_comment_id = Column(String(100))
    original_comment = Column(Text)
    reply_text = Column(Text)
    replied_at = Column(DateTime, default=utcnow)
    status = Column(String(20), default="sent")


class EngagementAction(Base):
    __tablename__ = "engagement_actions"

    id = Column(Integer, primary_key=True)
    instagram_media_id = Column(String(100), unique=True, nullable=False)
    action = Column(String(20), default="like")  # like, skipped
    hashtag = Column(String(100), nullable=True)
    score = Column(Float, nullable=True)
    skip_reason = Column(Text, nullable=True)
    comment_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True)
    action = Column(String(100))
    details = Column(Text, nullable=True)
    level = Column(String(20), default="info")
    created_at = Column(DateTime, default=utcnow)


class AgentSettings(Base):
    __tablename__ = "agent_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


def init_db():
    """Create all tables and seed default settings."""
    Base.metadata.create_all(engine)
    session = Session()
    
    defaults = {
        "image_source": Config.IMAGE_SOURCE,
        "post_interval_hours": str(Config.POST_INTERVAL_HOURS),
        "enable_comment_replies": str(Config.ENABLE_COMMENT_REPLIES).lower(),
        "max_posts_per_day": str(Config.MAX_POSTS_PER_DAY),
        "agent_persona": Config.AGENT_PERSONA,
        "scheduler_enabled": "false",
        "custom_instructions": "",
        "enable_engagement": "true",
        "engagement_hashtags": "cats,catsofinstagram,catlovers,kittens,catlife,meow,kitty,catoftheday",
        "likes_per_cycle": "5",
        "vip_accounts": "ghumoose,ffwow,navigator993",
    }

    for key, value in defaults.items():
        existing = session.query(AgentSettings).filter_by(key=key).first()
        if not existing:
            session.add(AgentSettings(key=key, value=value))

    session.commit()
    Session.remove()


def get_setting(key, default=None):
    session = Session()
    setting = session.query(AgentSettings).filter_by(key=key).first()
    Session.remove()
    return setting.value if setting else default


def set_setting(key, value):
    session = Session()
    setting = session.query(AgentSettings).filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        session.add(AgentSettings(key=key, value=value))
    session.commit()
    Session.remove()


def log_activity(action, details=None, level="info"):
    session = Session()
    session.add(ActivityLog(action=action, details=details, level=level))
    session.commit()
    Session.remove()
