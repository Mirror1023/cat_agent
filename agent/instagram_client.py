"""
Instagram Platform API client for publishing posts and managing comments.

Uses the Instagram API with Instagram Login (launched July 2024).
NO Facebook Page required — authenticates directly via Instagram.

API Base: https://graph.instagram.com/v21.0/
Scopes: instagram_business_basic, instagram_business_content_publish,
        instagram_business_manage_comments

Flow for publishing an image post:
1. POST /{ig-user-id}/media  — create a media container with image_url + caption
2. Poll GET /{container-id}?fields=status_code until status is FINISHED
3. POST /{ig-user-id}/media_publish — publish the container

The image MUST be publicly accessible via URL. For local images, you'll need to
either upload to a hosting service first or use a tunnel (e.g., ngrok).
"""

import time
import requests
from config import Config
from agent.models import log_activity

_RETRYABLE_STATUSES = {500, 502, 503, 504, 529}
_RETRY_DELAYS = [2, 5]  # seconds before attempt 2 and 3

IG_MAX_CAPTION_LENGTH = 2200
IG_MAX_HASHTAGS = 30


class InstagramClient:
    def __init__(self):
        self.access_token = Config.INSTAGRAM_ACCESS_TOKEN
        self.account_id = Config.INSTAGRAM_ACCOUNT_ID
        self.base_url = Config.GRAPH_API_BASE  # https://graph.instagram.com/v21.0

    def _url(self, path):
        return f"{self.base_url}/{path}"

    def _params(self, extra=None):
        params = {"access_token": self.access_token}
        if extra:
            params.update(extra)
        return params

    def _post_with_retry(self, url: str, data: dict, timeout: int = 30) -> requests.Response:
        """POST with exponential backoff retry for transient errors (5xx, network failures)."""
        delays = [0] + _RETRY_DELAYS
        last_exc = None
        for attempt, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            try:
                resp = requests.post(url, data=data, timeout=timeout)
                resp.raise_for_status()
                return resp
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in _RETRYABLE_STATUSES:
                    last_exc = e
                    if attempt < len(delays) - 1:
                        log_activity("ig_retry", f"Retrying after {e.response.status_code} (attempt {attempt + 1}/{len(delays)})", level="warning")
                        continue
                if e.response is not None:
                    try:
                        ig_error = e.response.json().get("error", {})
                        msg = ig_error.get("message") or e.response.text
                        code = ig_error.get("code", "")
                        subcode = ig_error.get("error_subcode", "")
                        detail = f"Instagram API error ({e.response.status_code}): {msg}"
                        if code:
                            detail += f" [code {code}"
                            if subcode:
                                detail += f", subcode {subcode}"
                            detail += "]"
                        raise requests.HTTPError(detail, response=e.response)
                    except (ValueError, AttributeError):
                        pass
                raise
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < len(delays) - 1:
                    log_activity("ig_retry", f"Retrying after network error (attempt {attempt + 1}/{len(delays)}): {type(e).__name__}", level="warning")
                    continue
                raise
        raise last_exc

    def validate_for_post(self, image_url: str, caption: str):
        """Validate caption and image URL before posting. Raises ValueError on failure."""
        if len(caption) > IG_MAX_CAPTION_LENGTH:
            raise ValueError(f"Caption too long: {len(caption)} chars (max {IG_MAX_CAPTION_LENGTH})")

        hashtag_count = sum(1 for w in caption.split() if w.startswith("#"))
        if hashtag_count > IG_MAX_HASHTAGS:
            raise ValueError(f"Too many hashtags: {hashtag_count} (max {IG_MAX_HASHTAGS})")

        try:
            resp = requests.head(image_url, timeout=10, allow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"URL does not point to an image (Content-Type: {content_type})")
        except requests.RequestException as e:
            raise ValueError(f"Image URL is not accessible: {e}")

    def create_media_container(self, image_url: str, caption: str) -> dict:
        """Step 1: Create a media container."""
        url = self._url(f"{self.account_id}/media")
        payload = self._params({
            "image_url": image_url,
            "caption": caption,
        })
        resp = self._post_with_retry(url, payload)
        data = resp.json()

        if "id" not in data:
            raise ValueError(f"Failed to create media container: {data}")

        log_activity("ig_container_created", f"Container ID: {data['id']}")
        return data

    def wait_for_container(self, container_id: str, max_wait: int = 60) -> str:
        """Step 2: Poll until container is ready."""
        url = self._url(container_id)
        start = time.time()

        while time.time() - start < max_wait:
            resp = requests.get(url, params=self._params({"fields": "status_code"}), timeout=15)
            resp.raise_for_status()
            status = resp.json().get("status_code", "UNKNOWN")

            if status == "FINISHED":
                return status
            elif status == "ERROR":
                raise ValueError(f"Container {container_id} failed with ERROR status")

            time.sleep(3)

        raise TimeoutError(f"Container {container_id} not ready after {max_wait}s")

    def publish_media(self, container_id: str) -> dict:
        """Step 3: Publish the container."""
        url = self._url(f"{self.account_id}/media_publish")
        payload = self._params({"creation_id": container_id})
        resp = self._post_with_retry(url, payload)
        data = resp.json()

        if "id" not in data:
            raise ValueError(f"Failed to publish media: {data}")

        log_activity("ig_post_published", f"Media ID: {data['id']}", level="success")
        return data

    def publish_post(self, image_url: str, caption: str) -> str:
        """Full publish flow: validate → create container → wait → publish. Returns media ID."""
        self.validate_for_post(image_url, caption)
        container = self.create_media_container(image_url, caption)
        container_id = container["id"]
        self.wait_for_container(container_id)
        result = self.publish_media(container_id)
        return result["id"]

    def get_media_comments(self, media_id: str) -> list:
        """Fetch comments on a specific post."""
        url = self._url(f"{media_id}/comments")
        resp = requests.get(
            url,
            params=self._params({"fields": "id,text,username,timestamp"}),
            timeout=15,
        )
        if not resp.ok:
            try:
                ig_error = resp.json().get("error", {})
                msg = ig_error.get("message") or resp.text
                code = ig_error.get("code", "")
                subcode = ig_error.get("error_subcode", "")
                detail = f"Instagram API error ({resp.status_code}): {msg}"
                if code:
                    detail += f" [code {code}"
                    if subcode:
                        detail += f", subcode {subcode}"
                    detail += "]"
            except Exception:
                detail = f"{resp.status_code} {resp.text}"
            raise requests.HTTPError(detail, response=resp)
        return resp.json().get("data", [])

    def reply_to_comment(self, comment_id: str, message: str) -> dict:
        """Reply to a specific comment."""
        url = self._url(f"{comment_id}/replies")
        payload = self._params({"message": message})
        resp = requests.post(url, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        log_activity("ig_comment_reply", f"Replied to {comment_id}: {message[:80]}...")
        return data

    def get_account_insights(self) -> dict:
        """Fetch basic account info via Instagram Platform API."""
        url = self._url(self.account_id)
        resp = requests.get(
            url,
            params=self._params({"fields": "username,followers_count,follows_count,media_count,biography,profile_picture_url"}),
            timeout=15,
        )
        if not resp.ok:
            error_body = resp.json() if resp.content else {}
            ig_error = error_body.get("error", {})
            msg = ig_error.get("message") or resp.text
            code = ig_error.get("code", "")
            subcode = ig_error.get("error_subcode", "")
            detail = f"Instagram API error ({resp.status_code}): {msg}"
            if code:
                detail += f" [code {code}"
                if subcode:
                    detail += f", subcode {subcode}"
                detail += "]"
            raise requests.HTTPError(detail, response=resp)
        return resp.json()

    def get_likes_stats(self) -> dict:
        """Paginate through all posts and return likes and comments stats."""
        total_likes = 0
        total_comments = 0
        post_count = 0
        url = self._url(f"{self.account_id}/media")
        params = self._params({"fields": "like_count,comments_count", "limit": 100})
        while url:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for post in data.get("data", []):
                total_likes += post.get("like_count", 0)
                total_comments += post.get("comments_count", 0)
                post_count += 1
            url = data.get("paging", {}).get("next")
            params = {}
        avg_likes = round(total_likes / post_count, 1) if post_count > 0 else 0
        avg_comments = round(total_comments / post_count, 1) if post_count > 0 else 0
        return {
            "total_likes": total_likes,
            "post_count": post_count,
            "avg_likes_per_post": avg_likes,
            "total_comments": total_comments,
            "avg_comments_per_post": avg_comments,
        }

    def get_recent_media(self, limit: int = 10) -> list:
        """Fetch recent posts."""
        url = self._url(f"{self.account_id}/media")
        resp = requests.get(
            url,
            params=self._params({
                "fields": "id,caption,media_url,timestamp,like_count,comments_count",
                "limit": limit,
            }),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def search_hashtag(self, hashtag: str) -> str:
        """Look up a hashtag and return its ID."""
        resp = requests.get(
            f"{self.base_url}/ig-hashtag-search",
            params=self._params({"user_id": self.account_id, "q": hashtag.lstrip("#")}),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0]["id"] if data else None

    def get_hashtag_media(self, hashtag_id: str, limit: int = 20) -> list:
        """Fetch recent image posts for a hashtag."""
        resp = requests.get(
            f"{self.base_url}/{hashtag_id}/recent_media",
            params=self._params({
                "user_id": self.account_id,
                "fields": "id,media_type,media_url,timestamp",
                "limit": limit,
            }),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def comment_on_media(self, media_id: str, message: str) -> bool:
        """Post a top-level comment on a media post. Requires instagram_business_manage_comments."""
        resp = requests.post(
            f"{self.base_url}/{media_id}/comments",
            data=self._params({"message": message}),
            timeout=15,
        )
        if not resp.ok:
            try:
                ig_error = resp.json().get("error", {})
                msg = ig_error.get("message") or resp.text
                code = ig_error.get("code", "")
                detail = f"Instagram API error ({resp.status_code}): {msg}"
                if code:
                    detail += f" [code {code}]"
            except Exception:
                detail = f"{resp.status_code} {resp.text}"
            raise requests.HTTPError(detail, response=resp)
        log_activity("ig_commented", f"Commented on {media_id}: {message[:60]}", level="info")
        return True

    def like_media(self, media_id: str) -> bool:
        """Like a media post. Requires instagram_manage_likes permission."""
        resp = requests.post(
            f"{self.base_url}/{media_id}/likes",
            data=self._params(),
            timeout=15,
        )
        if not resp.ok:
            try:
                ig_error = resp.json().get("error", {})
                msg = ig_error.get("message") or resp.text
                code = ig_error.get("code", "")
                detail = f"Instagram API error ({resp.status_code}): {msg}"
                if code:
                    detail += f" [code {code}]"
            except Exception:
                detail = f"{resp.status_code} {resp.text}"
            raise requests.HTTPError(detail, response=resp)
        log_activity("ig_liked", f"Liked media {media_id}", level="info")
        return True

    def get_user_media_by_username(self, username: str) -> list:
        """Fetch recent posts from another public business/creator account via Business Discovery API."""
        resp = requests.get(
            self._url(self.account_id),
            params=self._params({
                "fields": "business_discovery.fields(id,username,media.limit(12){id,media_type,media_url,timestamp})",
                "username": username.lstrip("@"),
            }),
            timeout=15,
        )
        if not resp.ok:
            try:
                ig_error = resp.json().get("error", {})
                msg = ig_error.get("message") or resp.text
                code = ig_error.get("code", "")
                detail = f"Instagram API error ({resp.status_code}): {msg}"
                if code:
                    detail += f" [code {code}]"
            except Exception:
                detail = f"{resp.status_code} {resp.text}"
            raise requests.HTTPError(detail, response=resp)
        discovery = resp.json().get("business_discovery", {})
        return discovery.get("media", {}).get("data", [])

    def get_all_media(self) -> list:
        """Paginate through all posts and return id, media_url, and timestamp."""
        results = []
        url = self._url(f"{self.account_id}/media")
        params = self._params({"fields": "id,media_url,timestamp", "limit": 100})
        while url:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("data", []))
            url = data.get("paging", {}).get("next")
            params = {}
        return results

    def exchange_short_lived_token(self, short_lived_token: str) -> dict:
        """
        Exchange a short-lived token (valid ~1 hour) for a long-lived token (valid 60 days).
        Returns dict with 'access_token', 'token_type', and 'expires_in'.
        Store the returned access_token in your .env as INSTAGRAM_ACCESS_TOKEN.
        """
        resp = requests.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": Config.INSTAGRAM_APP_SECRET,
                "access_token": short_lived_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        log_activity(
            "token_exchanged",
            f"Long-lived token obtained, expires in {data.get('expires_in', '?')}s",
            level="success",
        )
        return data

    def refresh_long_lived_token(self) -> dict:
        """
        Refresh a long-lived token before it expires (60-day lifespan).
        Call this every ~50 days to keep the token alive.
        Returns the new token data.
        """
        url = f"https://graph.instagram.com/refresh_access_token"
        resp = requests.get(url, params={
            "grant_type": "ig_refresh_token",
            "access_token": self.access_token,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        log_activity("token_refreshed", f"New token expires in {data.get('expires_in', '?')}s", level="success")
        return data

    def delete_post(self, media_id: str) -> bool:
        """Delete a published post from Instagram."""
        url = self._url(media_id)
        resp = requests.delete(url, params=self._params(), timeout=15)
        if not resp.ok:
            error_body = resp.json() if resp.content else {}
            ig_error = error_body.get("error", {})
            msg = ig_error.get("message") or resp.text
            code = ig_error.get("code", "")
            subcode = ig_error.get("error_subcode", "")
            detail = f"Instagram API error ({resp.status_code}): {msg}"
            if code:
                detail += f" [code {code}"
                if subcode:
                    detail += f", subcode {subcode}"
                detail += "]"
            raise requests.HTTPError(detail, response=resp)
        log_activity("ig_post_deleted", f"Deleted media ID: {media_id}", level="info")
        return True

    def test_connection(self) -> tuple:
        """Test if credentials are valid. Returns (success, message)."""
        try:
            info = self.get_account_insights()
            username = info.get("username", "unknown")
            followers = info.get("followers_count", 0)
            return True, f"Connected as @{username} ({followers:,} followers)"
        except requests.HTTPError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
