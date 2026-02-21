"""Authentication for the admin dashboard."""

from functools import wraps
from flask import session, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

_admin_password_hash = generate_password_hash(Config.ADMIN_PASSWORD)

def verify_password(password: str) -> bool:
    return check_password_hash(_admin_password_hash, password)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def login_user():
    session["authenticated"] = True
    session.permanent = True

def logout_user():
    session.clear()
