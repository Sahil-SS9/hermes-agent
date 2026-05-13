"""
Screenshot repurposing engine.
Transforms raw app screenshots into platform-specific marketing assets.
"""

import os
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from config import PLATFORM_FORMATS


def _get_font(size: int = 24) -> ImageFont.FreeTypeFont:
    """Load a font, falling back through common system fonts."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _add_brand_footer(
    img: Image.Image,
    brand_name: str,
    tagline: str,
    bg_color: tuple = (12, 12, 12),
    text_color: tuple = (255, 255, 255),
    accent_color: tuple = (251, 191, 36),  # Plenishd Yellow default
) -> Image.Image:
    """Add a branded footer bar to the bottom of the image."""
    footer_height = 80
    new_height = img.height + footer_height
    new_img = Image.new("RGBA", (img.width, new_height), bg_color)
    new_img.paste(img, (0, 0))
    
    draw = ImageDraw.Draw(new_img)
    
    # Brand name
    brand_font = _get_font(28)
    tagline_font = _get_font(16)
    
    # Draw brand name with accent underline
    draw.text((30, img.height + 15), brand_name, fill=accent_color, font=brand_font)
    draw.text((30, img.height + 48), tagline, fill=(180, 180, 180), font=tagline_font)
    
    # Small CTA on right
    cta_font = _get_font(14)
    cta_text = "Download the app →"
    bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_width = bbox[2] - bbox[0]
    draw.text(
        (img.width - cta_width - 30, img.height + 30),
        cta_text,
        fill=accent_color,
        font=cta_font,
    )
    
    return new_img


def _add_text_overlay(
    img: Image.Image,
    headline: str,
    subheadline: str = "",
    position: str = "top",
    headline_color: tuple = (255, 255, 255),
    shadow: bool = True,
) -> Image.Image:
    """Add headline text overlay to image with optional shadow for readability."""
    draw = ImageDraw.Draw(img)
    
    headline_font = _get_font(42)
    sub_font = _get_font(22)
    
    # Calculate text position
    padding = 40
    if position == "top":
        y_start = padding
    elif position == "bottom":
        y_start = img.height - 200
    else:
        y_start = img.height // 2 - 100
    
    # Draw shadow for readability
    if shadow:
        shadow_offset = 3
        for offset in [shadow_offset]:
            draw.text(
                (padding + offset, y_start + offset),
                headline,
                fill=(0, 0, 0, 180),
                font=headline_font,
            )
    
    # Draw headline
    draw.text((padding, y_start), headline, fill=headline_color, font=headline_font)
    
    # Draw subheadline
    if subheadline:
        y_sub = y_start + 60
        if shadow:
            draw.text(
                (padding + 2, y_sub + 2),
                subheadline,
                fill=(0, 0, 0, 180),
                font=sub_font,
            )
        draw.text((padding, y_sub), subheadline, fill=(220, 220, 220), font=sub_font)
    
    return img


def _crop_to_ratio(img: Image.Image, ratio: str) -> Image.Image:
    """Crop image to target aspect ratio, center-weighted."""
    ratios = {
        "1:1": (1, 1),
        "4:5": (4, 5),
        "9:16": (9, 16),
        "1.91:1": (1.91, 1),
        "16:9": (16, 9),
    }
    
    target_w, target_h = ratios.get(ratio, (1, 1))
    target_ratio = target_w / target_h
    
    img_ratio = img.width / img.height
    
    if img_ratio > target_ratio:
        # Image is wider, crop width
        new_width = int(img.height * target_ratio)
        left = (img.width - new_width) // 2
        img = img.crop((left, 0, left + new_width, img.height))
    else:
        # Image is taller, crop height
        new_height = int(img.width / target_ratio)
        top = (img.height - new_height) // 2
        img = img.crop((0, top, img.width, top + new_height))
    
    return img


def _resize_to_fit(img: Image.Image, target_size: tuple, upscale: bool = False) -> Image.Image:
    """Resize image to fit target dimensions, maintaining aspect ratio."""
    target_w, target_h = target_size
    
    # If image is smaller and we don't upscale, just return
    if not upscale and img.width <= target_w and img.height <= target_h:
        return img
    
    # Calculate scaling to fit within target
    scale_w = target_w / img.width
    scale_h = target_h / img.height
    scale = min(scale_w, scale_h)
    
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    
    return img.resize((new_w, new_h), Image.LANCZOS)


BRAND_CONFIG = {
    "matchdaymaestro": {
        "name": "MatchdayMaestro",
        "tagline": "Predict. Compete. Win.",
        "accent": (220, 38, 38),  # Red
        "bg": (18, 18, 18),
    },
    "plenishd": {
        "name": "Plenishd",
        "tagline": "Snap it · Say it · Stock it.",
        "accent": (251, 191, 36),  # Yellow
        "bg": (44, 42, 40),
    },
    "coachos": {
        "name": "CoachOS",
        "tagline": "Built for the coach on the sideline.",
        "accent": (34, 197, 94),  # Green
        "bg": (18, 18, 18),
    },
    "personal": {
        "name": "Sahil Saghir",
        "tagline": "Senior PM · Indie Developer · Building in Public",
        "accent": (59, 130, 246),  # Blue
        "bg": (12, 12, 12),
    },
}


def create_screenshot_asset(
    screenshot_path: str,
    brand: str,
    platform: str,
    headline: str = "",
    subheadline: str = "",
    add_footer: bool = True,
    add_text: bool = True,
    output_path: str = None,
) -> str:
    """
    Transform a raw screenshot into a platform-specific marketing asset.
    
    Args:
        screenshot_path: Path to raw screenshot
        brand: Brand key from BRAND_CONFIG
        platform: Platform key from PLATFORM_FORMATS
        headline: Optional headline overlay text
        subheadline: Optional subheadline text
        add_footer: Whether to add branded footer
        add_text: Whether to add text overlay
        output_path: Optional explicit output path
    
    Returns:
        Path to generated asset
    """
    # Load screenshot
    img = Image.open(screenshot_path).convert("RGBA")
    
    # Get platform format
    fmt = PLATFORM_FORMATS.get(platform, PLATFORM_FORMATS["twitter"])
    
    # Get brand config
    config = BRAND_CONFIG.get(brand, BRAND_CONFIG["personal"])
    
    # Step 1: Crop to platform aspect ratio
    img = _crop_to_ratio(img, fmt["image_ratio"])
    
    # Step 2: Resize to platform dimensions
    img = _resize_to_fit(img, fmt["image_size"], upscale=False)
    
    # Step 3: Add text overlay if requested
    if add_text and headline:
        img = _add_text_overlay(
            img, headline, subheadline,
            headline_color=(255, 255, 255),
        )
    
    # Step 4: Add branded footer
    if add_footer:
        img = _add_brand_footer(
            img,
            config["name"],
            config["tagline"],
            bg_color=config["bg"],
            accent_color=config["accent"],
        )
    
    # Step 5: Ensure final dimensions match platform exactly
    target_w, target_h = fmt["image_size"]
    if img.width != target_w or img.height != target_h:
        # Create canvas and center the image
        canvas = Image.new("RGBA", (target_w, target_h), config["bg"])
        x = (target_w - img.width) // 2
        y = (target_h - img.height) // 2
        canvas.paste(img, (x, y), img if img.mode == "RGBA" else None)
        img = canvas
    
    # Save
    if output_path is None:
        output_dir = Path.home() / "apps" / "content-engine" / "assets" / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{brand}_{platform}_{uuid.uuid4().hex}.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to RGB for JPEG compatibility, but keep PNG for quality
    if img.mode == "RGBA":
        # Create white background
        background = Image.new("RGBA", img.size, (255, 255, 255))
        img = Image.alpha_composite(background, img)
    
    img = img.convert("RGB")
    img.save(output_path, "PNG", optimize=True)
    
    return str(output_path)


def create_multi_screenshot_collage(
    screenshot_paths: list[str],
    brand: str,
    platform: str,
    headline: str = "",
    output_path: str = None,
) -> str:
    """
    Create a collage from multiple screenshots (e.g., app walkthrough).
    Arranges 2-4 screenshots in a grid.
    """
    if not screenshot_paths:
        raise ValueError("No screenshots provided")
    
    # Load and resize all screenshots to same size
    images = []
    max_w, max_h = 500, 500  # Base size per screenshot in collage
    
    for path in screenshot_paths:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        images.append(img)
    
    # Determine grid layout
    count = len(images)
    if count <= 2:
        cols, rows = count, 1
    elif count <= 4:
        cols, rows = 2, 2
    else:
        cols, rows = 3, (count + 2) // 3
    
    # Get platform format
    fmt = PLATFORM_FORMATS.get(platform, PLATFORM_FORMATS["twitter"])
    target_w, target_h = fmt["image_size"]
    
    # Calculate cell size
    gap = 20
    cell_w = (target_w - gap * (cols + 1)) // cols
    cell_h = (target_h - gap * (rows + 1)) // rows
    
    # Create canvas
    config = BRAND_CONFIG.get(brand, BRAND_CONFIG["personal"])
    canvas = Image.new("RGBA", (target_w, target_h), config["bg"])
    draw = ImageDraw.Draw(canvas)
    
    # Place images
    for i, img in enumerate(images):
        col = i % cols
        row = i // cols
        
        # Resize to fit cell
        img_ratio = img.width / img.height
        cell_ratio = cell_w / cell_h
        
        if img_ratio > cell_ratio:
            new_w = cell_w
            new_h = int(cell_w / img_ratio)
        else:
            new_h = cell_h
            new_w = int(cell_h * img_ratio)
        
        img = img.resize((new_w, new_h), Image.LANCZOS)
        
        # Center in cell
        x = gap + col * (cell_w + gap) + (cell_w - new_w) // 2
        y = gap + row * (cell_h + gap) + (cell_h - new_h) // 2
        
        # Add rounded rectangle background for each cell
        cell_bg = Image.new("RGBA", (cell_w, cell_h), (40, 40, 40, 200))
        canvas.paste(cell_bg, (gap + col * (cell_w + gap), gap + row * (cell_h + gap)))
        canvas.paste(img, (x, y), img)
    
    # Add headline if provided
    if headline:
        headline_font = _get_font(36)
        # Semi-transparent overlay at top
        overlay = Image.new("RGBA", (target_w, 80), (0, 0, 0, 180))
        canvas = Image.alpha_composite(canvas, overlay)
        draw = ImageDraw.Draw(canvas)
        draw.text((30, 20), headline, fill=(255, 255, 255), font=headline_font)
    
    # Add footer
    canvas = _add_brand_footer(
        canvas,
        config["name"],
        config["tagline"],
        bg_color=config["bg"],
        accent_color=config["accent"],
    )
    
    # Save
    if output_path is None:
        output_dir = Path.home() / "apps" / "content-engine" / "assets" / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{brand}_{platform}_collage_{uuid.uuid4().hex}.png"
    
    # Convert and save
    background = Image.new("RGBA", canvas.size, (255, 255, 255))
    canvas = Image.alpha_composite(background, canvas)
    canvas.convert("RGB").save(output_path, "PNG", optimize=True)
    
    return str(output_path)
