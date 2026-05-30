"""FAL.ai client for image and video generation.
Supports both Hermes native image_gen and direct API for video.

IMPORTANT: Every API call costs credits. Image generation is ~£0.005 each.
Video generation is ~£0.16-0.40 per 5-second clip. Use sparingly.
"""
import os
import time
import uuid
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    requests = None

FAL_KEY = os.getenv("FAL_KEY", "")

# Model endpoints on fal.ai
IMAGE_MODELS = {
    "z_image": "fal-ai/z-image/turbo",           # ~£0.008/img, fast + detailed
    "flux_klein": "fal-ai/flux-2/klein/9b",      # £0.0048/img, fast
    "krea_medium": "fal-ai/krea/v2/medium/text-to-image",  # ~£0.02/img, aesthetic detail
    "krea_large": "fal-ai/krea/v2/large/text-to-image",    # ~£0.03/img, max detail
    "flux_pro": "fal-ai/flux-2-pro",             # £0.024/img, quality
    "ideogram": "fal-ai/ideogram/v3",            # £0.024/img, typography
    "nano_banana": "fal-ai/nano-banana-pro",     # £0.12/img, text+reasoning
}

VIDEO_MODELS = {
    "wan_22_480p": "fal-ai/wan/v2.2/480p",       # ~£0.032/sec
    "wan_22_720p": "fal-ai/wan/v2.2/720p",       # ~£0.064/sec
    "wan_27": "fal-ai/wan/v2.7",                 # ~£0.08/sec premium
    "seedance_fast": "fal-ai/seedance/v2.0/fast", # ~£0.022/sec cheapest
}


def _headers() -> dict:
    return {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}


def _poll_queue_result(model_id: str, request_id: str, timeout: int = 120) -> Optional[dict]:
    """Poll async queue endpoint for result."""
    if not FAL_KEY or requests is None:
        return None
    poll_url = f"https://queue.fal.run/{model_id}/requests/{request_id}"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(poll_url, headers=_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "")
                if status == "COMPLETED":
                    return data
                elif status in ("FAILED", "CANCELLED"):
                    print(f"FAL queue failed: {status}")
                    return None
            time.sleep(3)
        except Exception as e:
            print(f"FAL poll error: {e}")
            return None
    print("FAL queue: polling timeout")
    return None


def generate_image(
    prompt: str,
    model: str = "flux_klein",
    aspect: str = "square",
    output_dir: str = "/home/kensei/repos/KenseiAgent/content_engine/output",
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate image via fal.ai. Returns file path or None."""
    if not FAL_KEY or requests is None:
        print("FAL_KEY not set or requests unavailable. Skipping image generation.")
        return None

    model_id = IMAGE_MODELS.get(model, IMAGE_MODELS["flux_klein"])

    # Aspect mapping per fal.ai spec
    aspect_map = {
        "square": "square_hd",
        "landscape": "landscape_16_9",
        "portrait": "portrait_16_9",
    }
    image_size = aspect_map.get(aspect, "square_hd")

    # Try sync endpoint first (for fast models)
    sync_url = f"https://fal.run/{model_id}"
    payload = {
        "prompt": prompt,
        "image_size": image_size,
        "num_images": 1,
        "enable_safety_checker": False,
    }

    try:
        r = requests.post(sync_url, json=payload, headers=_headers(), timeout=60)
        if r.status_code == 200:
            result = r.json()
        elif r.status_code in (202, 429):
            # Rate limited or queued — fall back to async
            print("FAL sync queued, switching to async poll...")
            queue_url = f"https://queue.fal.run/{model_id}"
            qr = requests.post(queue_url, json=payload, headers=_headers(), timeout=30)
            if qr.status_code != 200:
                print(f"FAL queue submit failed: {qr.status_code}")
                return None
            qdata = qr.json()
            request_id = qdata.get("request_id")
            if not request_id:
                print("FAL queue: no request_id")
                return None
            result = _poll_queue_result(model_id, request_id, timeout=120)
            if not result:
                return None
        else:
            print(f"FAL image failed: {r.status_code} {r.text[:200]}")
            return None

        # Extract image URL from response
        images = result.get("images", [])
        if not images and "output" in result:
            images = result["output"].get("images", [])
        if not images and "image" in result:
            images = [result["image"]]

        if not images:
            print(f"FAL image: no images in response. Keys: {list(result.keys())[:10]}")
            return None

        image_url = images[0].get("url") if isinstance(images[0], dict) else images[0]
        if not image_url:
            print("FAL image: no URL in first image")
            return None

        # Download
        img_r = requests.get(image_url, timeout=60)
        if img_r.status_code != 200:
            print(f"FAL image download failed: {img_r.status_code}")
            return None

        out_path = Path(output_dir) / "fal_images"
        out_path.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{model}_{str(uuid.uuid4())[:8]}.png"
        fpath = out_path / fname
        fpath.write_bytes(img_r.content)
        print(f"FAL image saved: {fpath} ({len(img_r.content)} bytes)")
        return str(fpath)

    except Exception as e:
        print(f"FAL image generation error: {e}")
        return None


def generate_video(
    prompt: str,
    model: str = "wan_22_480p",
    duration: int = 5,
    output_dir: str = "/home/kensei/repos/KenseiAgent/content_engine/output",
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate video via fal.ai. Returns file path or None."""
    if not FAL_KEY or requests is None:
        print("FAL_KEY not set. Skipping video generation.")
        return None

    model_id = VIDEO_MODELS.get(model, VIDEO_MODELS["wan_22_480p"])
    # Video models are slower — use queue endpoint
    queue_url = f"https://queue.fal.run/{model_id}"
    payload = {
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": "16:9",
    }

    try:
        qr = requests.post(queue_url, json=payload, headers=_headers(), timeout=30)
        if qr.status_code != 200:
            print(f"FAL video queue failed: {qr.status_code} {qr.text[:200]}")
            return None

        qdata = qr.json()
        request_id = qdata.get("request_id")
        if not request_id:
            print("FAL video: no request_id")
            return None

        print(f"FAL video queued: {request_id}, polling...")
        result = _poll_queue_result(model_id, request_id, timeout=300)
        if not result:
            return None

        # Extract video URL
        video_url = result.get("video", {}).get("url")
        if not video_url:
            video_url = result.get("output", {}).get("video", {}).get("url")
        if not video_url:
            print(f"FAL video: no URL. Keys: {list(result.keys())[:10]}")
            return None

        vid_r = requests.get(video_url, timeout=120)
        if vid_r.status_code != 200:
            return None

        out_path = Path(output_dir) / "fal_videos"
        out_path.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{model}_{str(uuid.uuid4())[:8]}.mp4"
        fpath = out_path / fname
        fpath.write_bytes(vid_r.content)
        print(f"FAL video saved: {fpath} ({len(vid_r.content)} bytes)")
        return str(fpath)

    except Exception as e:
        print(f"FAL video generation error: {e}")
        return None


def generate_image_from_text_card(
    brand: str,
    body_text: str,
    output_dir: str = "/home/kensei/repos/KenseiAgent/content_engine/output",
) -> Optional[str]:
    """Generate a stylised image from a text card description. Uses flux_klein for speed."""
    prompt = f"Social media card, dark background, {brand} branding, text: {body_text[:120]}. Minimal, modern, high contrast, no watermark."
    return generate_image(prompt, model="flux_klein", aspect="square", output_dir=output_dir)
