"""
Multi-source image fetcher for the cat agent.
Supports: The Cat API, DALL-E generation, and local image folder.

IMPORTANT: Instagram API requires a publicly accessible image URL.
For local images, upload to an image host (Imgur, Cloudinary, S3) or use ngrok.
"""

import os
import random
import shutil
import requests
from datetime import datetime
from pathlib import Path
from config import Config
from agent.models import get_setting, log_activity


class ImageSourcer:
    """Fetches cat images from the configured source."""

    def __init__(self):
        self.local_dir = Path(Config.LOCAL_IMAGES_DIR)

    def get_image(self, source: str = None, used_urls: set = None) -> dict:
        source = source or get_setting("image_source", Config.IMAGE_SOURCE)
        used_urls = used_urls or set()

        if source == "random":
            available = ["cat_api"]
            if Config.OPENAI_API_KEY:
                available.append("dalle")
            if self._has_local_images():
                available.append("local")
            if Config.PEXELS_API_KEY:
                available.append("pexels")
            # local_video excluded from random: requires upload_to_hosting() to be implemented first
            source = random.choice(available)

        if source == "cat_api":
            return self._from_cat_api(used_urls)
        elif source == "dalle":
            return self._from_dalle(used_urls)
        elif source == "local":
            return self._from_local(used_urls)
        elif source == "pexels":
            return self._from_pexels(used_urls)
        elif source == "local_video":
            return self._from_local_video(used_urls)
        else:
            log_activity("image_source_unknown", f"Unknown source: {source}", level="warning")
            return self._from_cat_api(used_urls)

    def _from_cat_api(self, used_urls: set = None) -> dict:
        used_urls = used_urls or set()
        max_attempts = 10
        last_result = None
        for attempt in range(max_attempts):
            try:
                resp = requests.get(
                    "https://api.thecatapi.com/v1/images/search",
                    params={"size": "full", "mime_types": "jpg,png"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    raise ValueError("Empty response from Cat API")
                image = data[0]
                url = image["url"]
                breeds = image.get("breeds", [])
                context = breeds[0]["name"] if breeds else "a cute cat"
                last_result = {"url": url, "source": "cat_api", "context": context}
                if url not in used_urls:
                    log_activity("image_fetched", f"Cat API: {url}", level="info")
                    return last_result
                log_activity("image_duplicate_skipped", f"Cat API: already posted, retrying ({attempt + 1}/{max_attempts})", level="info")
            except Exception as e:
                log_activity("image_fetch_error", f"Cat API: {e}", level="error")
                raise
        log_activity("image_dedup_exhausted", "Could not find a fresh Cat API image after 10 attempts; reusing last", level="warning")
        return last_result

    def _from_dalle(self, used_urls: set = None) -> dict:
        if not Config.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")
        used_urls = used_urls or set()
        try:
            from openai import OpenAI
            from agent.caption_generator import CaptionGenerator
            captioner = CaptionGenerator()
            prompt = captioner.generate_image_prompt()
            client = OpenAI(api_key=Config.OPENAI_API_KEY)
            response = client.images.generate(model="dall-e-3", prompt=prompt, size="1024x1024", quality="standard", n=1)
            url = response.data[0].url
            if url in used_urls:
                log_activity("image_duplicate_skipped", "DALL-E: duplicate URL (extremely rare); regenerating", level="warning")
                response = client.images.generate(model="dall-e-3", prompt=prompt, size="1024x1024", quality="standard", n=1)
                url = response.data[0].url
            log_activity("image_generated", f"DALL-E: {prompt[:80]}...", level="success")
            return {"url": url, "source": "dalle", "context": prompt}
        except Exception as e:
            log_activity("image_gen_error", f"DALL-E: {e}", level="error")
            raise

    def _from_local(self, used_urls: set = None) -> dict:
        if not self._has_local_images():
            raise FileNotFoundError(f"No images found in {self.local_dir}. Add .jpg, .png, or .webp files to images/local/")
        used_urls = used_urls or set()
        valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        images = [f for f in self.local_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_extensions]
        used_filenames = {Path(u[len("LOCAL:"):]).name for u in used_urls if u.startswith("LOCAL:")}
        fresh = [f for f in images if f.name not in used_filenames]
        if not fresh:
            log_activity("local_images_exhausted", f"All {len(images)} local images have been posted. Starting the rotation over.", level="warning")
            fresh = images
        chosen = random.choice(fresh)
        log_activity("image_local", f"Selected: {chosen.name}")
        return {"url": f"LOCAL:{chosen}", "source": "local", "context": f"local image: {chosen.stem}", "local_path": str(chosen)}

    def _has_local_images(self) -> bool:
        if not self.local_dir.exists():
            return False
        valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        return any(f.suffix.lower() in valid_extensions for f in self.local_dir.iterdir() if f.is_file())

    def _has_local_videos(self) -> bool:
        if not self.local_dir.exists():
            return False
        video_extensions = {".mp4", ".mov"}
        return any(f.suffix.lower() in video_extensions for f in self.local_dir.iterdir() if f.is_file())

    def get_local_video_count(self) -> int:
        if not self.local_dir.exists():
            return 0
        video_extensions = {".mp4", ".mov"}
        return sum(1 for f in self.local_dir.iterdir() if f.is_file() and f.suffix.lower() in video_extensions)

    def _pick_hd_portrait_file(self, video_files: list) -> str:
        """Pick the best portrait HD video URL from a Pexels video_files array."""
        portrait_hd = [
            vf for vf in video_files
            if vf.get("quality") == "hd" and vf.get("height", 0) > vf.get("width", 0)
        ]
        if portrait_hd:
            return portrait_hd[0]["link"]
        # Fallback: any HD, then any portrait, then first available
        hd_files = [vf for vf in video_files if vf.get("quality") == "hd"]
        if hd_files:
            return hd_files[0]["link"]
        portrait_files = [vf for vf in video_files if vf.get("height", 0) > vf.get("width", 0)]
        if portrait_files:
            return portrait_files[0]["link"]
        return video_files[0]["link"] if video_files else ""

    def _from_pexels(self, used_urls: set = None) -> dict:
        if not Config.PEXELS_API_KEY:
            raise ValueError("Pexels API key not configured. Set PEXELS_API_KEY in .env")
        used_urls = used_urls or set()
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": Config.PEXELS_API_KEY},
                params={"query": "cats", "per_page": 15, "orientation": "portrait"},
                timeout=15,
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            for video in videos:
                video_files = video.get("video_files", [])
                if not video_files:
                    continue
                url = self._pick_hd_portrait_file(video_files)
                if not url or url in used_urls:
                    continue
                context = f"cat video from Pexels by {video.get('user', {}).get('name', 'unknown')}"
                thumbnail_url = video.get("image", "")
                log_activity("video_fetched", f"Pexels: {url}", level="info")
                return {"url": url, "source": "pexels", "context": context, "media_type": "video", "thumbnail_url": thumbnail_url}
            # All used — reuse the first available result without a second HTTP call
            for video in videos:
                video_files = video.get("video_files", [])
                if not video_files:
                    continue
                url = self._pick_hd_portrait_file(video_files)
                if not url:
                    continue
                context = f"cat video from Pexels by {video.get('user', {}).get('name', 'unknown')}"
                thumbnail_url = video.get("image", "")
                log_activity("video_dedup_exhausted", "All Pexels results used; reusing first", level="warning")
                return {"url": url, "source": "pexels", "context": context, "media_type": "video", "thumbnail_url": thumbnail_url}
            raise ValueError("No usable video files returned from Pexels")
        except Exception as e:
            log_activity("pexels_fetch_error", str(e), level="error")
            raise

    def _pexels_candidates(self, used_urls: set = None) -> list:
        """Fetch up to 5 portrait cat video candidates from Pexels."""
        if not Config.PEXELS_API_KEY:
            raise ValueError("Pexels API key not configured. Set PEXELS_API_KEY in .env")
        used_urls = used_urls or set()
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": Config.PEXELS_API_KEY},
                params={"query": "cats", "per_page": 15, "orientation": "portrait"},
                timeout=15,
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            candidates = []
            for video in videos:
                video_files = video.get("video_files", [])
                if not video_files:
                    continue
                url = self._pick_hd_portrait_file(video_files)
                if not url or url in used_urls:
                    continue
                context = f"cat video from Pexels by {video.get('user', {}).get('name', 'unknown')}"
                thumbnail_url = video.get("image", "")
                candidates.append({"url": url, "source": "pexels", "context": context, "media_type": "video", "thumbnail_url": thumbnail_url})
                if len(candidates) >= 5:
                    break
            if not candidates:
                # All results already used — reuse first valid one without a second HTTP call
                log_activity("pexels_candidates_all_used", "All Pexels results were duplicates; reusing first", level="warning")
                for video in videos:
                    video_files = video.get("video_files", [])
                    if not video_files:
                        continue
                    url = self._pick_hd_portrait_file(video_files)
                    if not url:
                        continue
                    context = f"cat video from Pexels by {video.get('user', {}).get('name', 'unknown')}"
                    thumbnail_url = video.get("image", "")
                    return [{"url": url, "source": "pexels", "context": context, "media_type": "video", "thumbnail_url": thumbnail_url}]
                raise ValueError("No usable video files returned from Pexels")
            log_activity("pexels_candidates_fetched", f"Fetched {len(candidates)} Pexels video candidates", level="info")
            return candidates
        except Exception as e:
            log_activity("pexels_fetch_error", str(e), level="error")
            raise

    def _from_local_video(self, used_urls: set = None) -> dict:
        if not self._has_local_videos():
            raise FileNotFoundError(f"No videos found in {self.local_dir}. Add .mp4 or .mov files to images/local/")
        used_urls = used_urls or set()
        video_extensions = {".mp4", ".mov"}
        videos = [f for f in self.local_dir.iterdir() if f.is_file() and f.suffix.lower() in video_extensions]
        used_filenames = {Path(u[len("LOCAL:"):]).name for u in used_urls if u.startswith("LOCAL:")}
        fresh = [f for f in videos if f.name not in used_filenames]
        if not fresh:
            log_activity("local_videos_exhausted", f"All {len(videos)} local videos have been posted. Starting rotation over.", level="warning")
            fresh = videos
        chosen = random.choice(fresh)
        log_activity("video_local", f"Selected: {chosen.name}")
        return {"url": f"LOCAL:{chosen}", "source": "local_video", "context": f"local video: {chosen.stem}", "media_type": "video", "local_path": str(chosen)}

    def _local_video_candidates(self, used_urls: set) -> list:
        """Return up to 5 randomly sampled unused local video files."""
        if not self._has_local_videos():
            raise FileNotFoundError(f"No videos found in {self.local_dir}. Add .mp4 or .mov files to images/local/")
        video_extensions = {".mp4", ".mov"}
        videos = [f for f in self.local_dir.iterdir() if f.is_file() and f.suffix.lower() in video_extensions]
        used_filenames = {Path(u[len("LOCAL:"):]).name for u in used_urls if u.startswith("LOCAL:")}
        fresh = [f for f in videos if f.name not in used_filenames]
        if not fresh:
            log_activity("local_videos_exhausted", f"All {len(videos)} local videos posted; restarting rotation", level="warning")
            fresh = videos
        chosen = random.sample(fresh, min(5, len(fresh)))
        log_activity("local_video_candidates_sampled", f"Sampled {len(chosen)} local video candidates", level="info")
        return [{"url": f"LOCAL:{f}", "source": "local_video", "context": f"local video: {f.stem}", "media_type": "video", "local_path": str(f)} for f in chosen]

    def upload_to_hosting(self, local_path: str) -> str:
        raise NotImplementedError(
            "Local image hosting not configured. Either:\n"
            "1. Implement upload_to_hosting() with your preferred service\n"
            "2. Use 'cat_api' or 'dalle' as your image source\n"
            "3. Set up ngrok to serve local files publicly"
        )

    def get_image_candidates(self, source: str = None, used_urls: set = None) -> list:
        """Fetch up to 5 candidate images/videos for selection. DALL-E returns 1 (already high quality)."""
        source = source or get_setting("image_source", Config.IMAGE_SOURCE)
        used_urls = used_urls or set()

        if source == "random":
            available = ["cat_api"]
            if Config.OPENAI_API_KEY:
                available.append("dalle")
            if self._has_local_images():
                available.append("local")
            if Config.PEXELS_API_KEY:
                available.append("pexels")
            # local_video excluded from random: requires upload_to_hosting() to be implemented first
            source = random.choice(available)

        if source == "dalle":
            return [self._from_dalle(used_urls)]
        elif source == "local":
            return self._local_candidates(used_urls)
        elif source == "pexels":
            return self._pexels_candidates(used_urls)
        elif source == "local_video":
            return self._local_video_candidates(used_urls)
        else:
            return self._cat_api_candidates(used_urls)

    def _cat_api_candidates(self, used_urls: set) -> list:
        """Fetch up to 5 fresh breed-filtered images from Cat API in one request."""
        try:
            resp = requests.get(
                "https://api.thecatapi.com/v1/images/search",
                params={"limit": 5, "has_breeds": 1, "mime_types": "jpg,png", "size": "full"},
                timeout=15,
            )
            resp.raise_for_status()
            candidates = []
            for image in resp.json():
                url = image["url"]
                if url in used_urls:
                    continue
                breeds = image.get("breeds", [])
                context = breeds[0]["name"] if breeds else "a cute cat"
                candidates.append({"url": url, "source": "cat_api", "context": context})
            if not candidates:
                log_activity("cat_api_candidates_all_used", "All 5 results were duplicates; falling back", level="warning")
                return [self._from_cat_api(used_urls)]
            log_activity("cat_api_candidates_fetched", f"Fetched {len(candidates)} fresh candidates for selection", level="info")
            return candidates
        except Exception as e:
            log_activity("image_fetch_error", f"Cat API candidates: {e}", level="error")
            raise

    def _local_candidates(self, used_urls: set) -> list:
        """Return up to 5 randomly sampled unused local images."""
        if not self._has_local_images():
            raise FileNotFoundError(f"No images found in {self.local_dir}. Add .jpg, .png, or .webp files to images/local/")
        valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        images = [f for f in self.local_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_extensions]
        used_filenames = {Path(u[len("LOCAL:"):]).name for u in used_urls if u.startswith("LOCAL:")}
        fresh = [f for f in images if f.name not in used_filenames]
        if not fresh:
            log_activity("local_images_exhausted", f"All {len(images)} local images posted; restarting rotation", level="warning")
            fresh = images
        chosen = random.sample(fresh, min(5, len(fresh)))
        log_activity("local_candidates_sampled", f"Sampled {len(chosen)} local candidates for selection", level="info")
        return [{"url": f"LOCAL:{f}", "source": "local", "context": f"local image: {f.stem}", "local_path": str(f)} for f in chosen]

    def save_to_history(self, image_url: str, media_id: str = None, source: str = "unknown") -> None:
        """Download or copy the posted image into images/history/."""
        try:
            history_dir = Path(Config.LOCAL_IMAGES_DIR).parent / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            suffix = f"_{media_id}" if media_id else ""
            if image_url.startswith("LOCAL:"):
                src = Path(image_url[len("LOCAL:"):])
                ext = src.suffix or ".jpg"
                dest = history_dir / f"{ts}{suffix}{ext}"
                shutil.copy2(src, dest)
            else:
                resp = requests.get(image_url, timeout=60, stream=True)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = ".jpg"
                elif "png" in content_type:
                    ext = ".png"
                elif "video" in content_type or "mp4" in content_type:
                    ext = ".mp4"
                else:
                    ext = ".jpg"
                dest = history_dir / f"{ts}{suffix}{ext}"
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            log_activity("image_history_saved", f"Saved to history: {dest.name} (source: {source})", level="info")
        except Exception as e:
            log_activity("image_history_error", f"Failed to save image to history: {e}", level="warning")

    def get_local_image_count(self) -> int:
        if not self.local_dir.exists():
            return 0
        valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        return sum(1 for f in self.local_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_extensions)
