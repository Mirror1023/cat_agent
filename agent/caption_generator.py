"""
Caption & hashtag generator powered by Claude (Anthropic).
Generates engaging, on-brand captions based on the agent's persona
and any custom instructions from the admin.
"""

import json
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import anthropic
from config import Config
from agent.models import get_setting, log_activity

_CAPTION_RETRY_DELAYS = [2, 5]  # seconds before attempt 2 and 3


class CaptionGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-20250514"

    def _get_system_prompt(self) -> str:
        persona = get_setting("agent_persona", Config.AGENT_PERSONA)
        custom_instructions = get_setting("custom_instructions", "")

        system = f"""{persona}

You are writing Instagram captions for a cat-themed account.

RULES:
- Keep captions engaging, fun, and authentic
- Include 1-2 relevant emojis naturally in the caption
- Keep captions between 1-4 sentences unless instructed otherwise
- Generate exactly 15-20 relevant hashtags (mix of popular and niche cat hashtags)
- Never use offensive or controversial content
- Stay on brand — everything should be about cats, kittens, and cat culture

RESPOND IN JSON FORMAT ONLY:
{{"caption": "your caption here", "hashtags": "#tag1 #tag2 #tag3 ..."}}"""

        if custom_instructions.strip():
            system += f"\n\nADDITIONAL INSTRUCTIONS FROM ADMIN:\n{custom_instructions}"

        return system

    def generate_caption(self, context: str = None, image_url: str = None) -> dict:
        now_nyc = datetime.now(ZoneInfo("America/New_York"))
        day_time = now_nyc.strftime("%A, %B %-d at %-I:%M %p EST")
        text = f"Generate an Instagram caption and hashtags for this cat photo. Base the caption on what you actually see in the image. Today is {day_time}."
        if context:
            text += f"\n\nAdditional context: {context}"

        use_vision = image_url and not image_url.startswith("LOCAL:")
        if use_vision:
            content = [
                {"type": "image", "source": {"type": "url", "url": image_url}},
                {"type": "text", "text": text},
            ]
        else:
            content = text

        try:
            delays = [0] + _CAPTION_RETRY_DELAYS
            for attempt, delay in enumerate(delays):
                if delay:
                    time.sleep(delay)
                try:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=500,
                        system=self._get_system_prompt(),
                        messages=[{"role": "user", "content": content}],
                    )
                    break
                except anthropic.APIStatusError as e:
                    if e.status_code == 529 and attempt < len(delays) - 1:
                        log_activity("caption_retry", f"Claude overloaded, retrying (attempt {attempt + 1}/{len(delays)})", level="warning")
                        continue
                    raise

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            result = json.loads(text)
            log_activity("caption_generated", f"Caption: {result.get('caption', '')[:80]}...", level="success")
            return {"caption": result.get("caption", ""), "hashtags": result.get("hashtags", "")}

        except json.JSONDecodeError:
            log_activity("caption_parse_error", f"Raw response: {text[:200]}", level="warning")
            return {"caption": text[:200] if text else "Another purrfect day! 🐱", "hashtags": "#cats #catsofinstagram #catlovers #meow #kitty"}
        except Exception as e:
            log_activity("caption_error", str(e), level="error")
            raise

    def select_best_image(self, candidates: list) -> dict:
        """Use Claude vision to score candidates and return the most engaging one."""
        if len(candidates) == 1:
            return candidates[0]

        scorable = [c for c in candidates if not c["url"].startswith("LOCAL:")]
        if not scorable:
            chosen = random.choice(candidates)
            log_activity("image_selection_local", "All candidates are local; picked randomly", level="info")
            return chosen

        content = []
        for i, c in enumerate(scorable):
            content.append({"type": "image", "source": {"type": "url", "url": c["url"]}})
            content.append({"type": "text", "text": f"Image {i + 1} ({c.get('context', 'cat')})"})

        content.append({"type": "text", "text": (
            f"Pick the best cat photo from these {len(scorable)} images for Instagram. "
            "Score each 1-10 (cuteness, quality, engagement). Discard blurry or boring ones. "
            'Reply in JSON only, keep all strings under 20 words: '
            '{"scores": [{"image": 1, "score": 8}], "best": 1, "reason": "short reason"}'
        )})

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                messages=[{"role": "user", "content": content}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            result = json.loads(raw)
            best_idx = max(0, min(int(result.get("best", 1)) - 1, len(scorable) - 1))
            scores = result.get("scores", [{}])
            score = scores[best_idx].get("score", "?") if best_idx < len(scores) else "?"
            log_activity("image_selected", f"Picked image {best_idx + 1}/{len(scorable)}, score {score}/10 — {result.get('reason', '')[:80]}", level="success")
            return scorable[best_idx]
        except Exception as e:
            log_activity("image_selection_error", f"Falling back to first candidate: {e}", level="warning")
            return scorable[0]

    def generate_comment_reply(self, comment_text: str, post_caption: str = "") -> str:
        persona = get_setting("agent_persona", Config.AGENT_PERSONA)
        custom_instructions = get_setting("custom_instructions", "")

        system = f"""{persona}

You are replying to comments on your Instagram cat account.

RULES:
- Be warm, friendly, and engaging
- Keep replies short (1-2 sentences max)
- Use 1 emoji max
- If the comment is negative or spam, reply politely or just say thanks
- Never be rude, controversial, or off-brand
- Do not reveal you are an AI or bot

Return ONLY the reply text, nothing else."""

        if custom_instructions.strip():
            system += f"\n\nADDITIONAL INSTRUCTIONS FROM ADMIN:\n{custom_instructions}"

        user_msg = f'Comment on your post: "{comment_text}"'
        if post_caption:
            user_msg += f'\n\nYour post caption was: "{post_caption}"'
        user_msg += "\n\nWrite a short, friendly reply:"

        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=150, system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            reply = response.content[0].text.strip().strip('"')
            log_activity("reply_generated", f"To: '{comment_text[:50]}' -> '{reply[:50]}'")
            return reply
        except Exception as e:
            log_activity("reply_error", str(e), level="error")
            return "Thank you! 😸"

    def generate_image_prompt(self) -> str:
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=200,
                system="You generate creative, detailed image prompts for AI image generation. "
                       "Focus on cats in interesting, beautiful, or funny scenarios. "
                       "Return ONLY the prompt text, nothing else. Keep it under 100 words.",
                messages=[{"role": "user", "content": "Generate a creative image prompt featuring a cat. Make it visually interesting and Instagram-worthy."}],
            )
            prompt = response.content[0].text.strip()
            log_activity("image_prompt_generated", prompt[:100])
            return prompt
        except Exception as e:
            log_activity("image_prompt_error", str(e), level="error")
            return "A fluffy orange tabby cat sitting in a sunbeam on a cozy windowsill, soft warm lighting, photography style"
