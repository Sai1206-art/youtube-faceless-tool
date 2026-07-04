"""
Script Generator — Uses GPT-4o to analyze product photos, video reference,
and user prompt to generate a structured video script.

Output: Structured JSON with scene-by-scene breakdown.
"""

import json
import base64
import os
from typing import Optional
from openai import OpenAI

from app.config import (
    OPENAI_API_KEY, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE,
    TEMP_DIR, MAX_VIDEO_DURATION, TARGET_DURATION
)


class ScriptGenerator:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def _encode_image(self, image_path: str) -> str:
        """Encode an image file to base64 for the API."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _encode_video_frames(self, video_path: str, max_frames: int = 4) -> list[str]:
        """
        Extract key frames from the reference video and encode to base64.
        We sample frames at evenly-spaced intervals to give GPT-4o a sense
        of the video's visual style/pacing.
        """
        import cv2

        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            cap.release()
            return []

        # Sample evenly-spaced frames
        step = max(total_frames // max_frames, 1)
        frames = []
        for i in range(0, total_frames, step):
            if len(frames) >= max_frames:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if ret:
                _, buffer = cv2.imencode(".jpg", frame)
                frames.append(base64.b64encode(buffer).decode("utf-8"))
        cap.release()
        return frames

    def generate_script(
        self,
        prompt: str,
        product_images: list[str],
        affiliate_link: Optional[str] = None,
        reference_video_path: Optional[str] = None,
        extra_context: Optional[str] = None,
    ) -> dict:
        """
        Generate a structured video script from user inputs.

        Args:
            prompt: User's description of what kind of video they want
            product_images: List of file paths to product photos
            affiliate_link: Optional affiliate URL to include in description
            reference_video_path: Optional path to a reference video
            extra_context: Any additional text context

        Returns:
            dict with keys: title, description, tags, scenes[]
        """
        # ─── Build the message content ───────────────────────
        content = []

        # --- Text instructions ---
        context_parts = []
        context_parts.append(f"User prompt: {prompt}")
        if affiliate_link:
            context_parts.append(f"Affiliate link to include in YouTube description: {affiliate_link}")
        if extra_context:
            context_parts.append(f"Additional context: {extra_context}")

        text_instruction = f"""
You are an expert YouTube scriptwriter for faceless tech product videos.
Analyze the product images{', and the reference video frames' if reference_video_path else ''} provided.

Create a complete video script for a {TARGET_DURATION}-second (max {MAX_VIDEO_DURATION}s) YouTube video.

## OUTPUT FORMAT — respond with ONLY valid JSON, no markdown, no extra text:

{{
  "title": "SEO-optimized YouTube title (max 70 chars)",
  "description": "Full YouTube description. If an affiliate link is provided, put it in the FIRST 2 LINES with a call-to-action like 'Get the [Product Name] here:'. Then add 2-3 paragraphs about the video content. Include relevant hashtags at the bottom.",
  "tags": ["tag1", "tag2", "tag3", ...],
  "category": "Science & Technology",
  "scenes": [
    {{
      "scene_number": 1,
      "duration_seconds": 5,
      "voiceover": "The exact text the TTS will read for this scene",
      "visual_description": "Description of what visual to show (used for stock footage search)",
      "text_overlay": "Short text to display on screen (max 8 words)",
      "image_source": "stock" | "product",
      "image_index": null
    }}
  ]
}}

## SCRIPT GUIDELINES:
- Hook in first 3 seconds (scene 1)
- Total duration of all scenes should add up to {TARGET_DURATION} seconds (max {MAX_VIDEO_DURATION}s)
- 8-15 scenes total
- Voiceover should be conversational, energetic, no robotic phrasing
- Vary image_source: use "product" for product photos, "stock" for stock footage
- For "product" scenes, set image_index to the photo number (0-based) to use
- Visual descriptions for stock footage should be search-friendly terms
- Text overlays should be punchy — key specs, feature names, benefits
- Do NOT mention prices unless the user explicitly asks
- Script in English unless prompt specifies otherwise

## AFFILIATE LINK HANDLING:
- If an affiliate link is provided, it MUST appear in the first 2 lines of the description
- Format: "🛒 Get the [Product Name] here: [affiliate_link]"
- Do NOT mention the affiliate link in the voiceover — only in description
{'- An affiliate link is provided — include it in the description.' if affiliate_link else '- No affiliate link provided — do not include one.'}

## Context:
{chr(10).join(context_parts)}
"""
        content.append({"type": "text", "text": text_instruction})

        # --- Product images ---
        for idx, img_path in enumerate(product_images):
            b64 = self._encode_image(img_path)
            ext = os.path.splitext(img_path)[1].lstrip(".").lower()
            mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            })

        # --- Reference video frames ---
        if reference_video_path and os.path.exists(reference_video_path):
            frames = self._encode_video_frames(reference_video_path)
            for frame_b64 in frames:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}
                })

        # ─── Call GPT-4o ─────────────────────────────────────
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": content
                }
            ],
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"}
        )

        script_data = json.loads(response.choices[0].message.content)

        # ─── Validation & fixes ──────────────────────────────
        total_duration = sum(s["duration_seconds"] for s in script_data.get("scenes", []))
        if total_duration > MAX_VIDEO_DURATION:
            # Scale down all scenes proportionally
            scale = MAX_VIDEO_DURATION / total_duration
            for scene in script_data["scenes"]:
                scene["duration_seconds"] = max(3, int(scene["duration_seconds"] * scale))
            script_data["_scaled_down"] = True

        # Store affiliate link for later use
        if affiliate_link:
            script_data["affiliate_link"] = affiliate_link

        return script_data
