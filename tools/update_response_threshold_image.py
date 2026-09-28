from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/weekly_summary/source_figures/2026-8-9_LLM局部重调度方案报告__image1.png"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", size)


def main() -> None:
    image = Image.open(SOURCE).convert("RGB")
    draw = ImageDraw.Draw(image)

    # Cover only the old threshold tokens, preserving the surrounding diagram.
    draw.rectangle((817, 208, 878, 233), fill=(255, 255, 255))
    draw.text((819, 216), "90min 阈值", font=font(12), fill=(45, 49, 66))

    header_fill = (27, 58, 107)
    draw.rectangle((402, 280, 448, 304), fill=header_fill)
    draw.text((405, 283), "90min)", font=font(15), fill=(255, 255, 255))
    draw.rectangle((988, 280, 1040, 304), fill=header_fill)
    draw.text((991, 283), "90min)", font=font(15), fill=(255, 255, 255))

    footer_fill = (240, 244, 255)
    draw.rectangle((354, 800, 394, 817), fill=footer_fill)
    draw.text((358, 804), "90min,", font=font(8), fill=(45, 49, 66))

    image.save(SOURCE)


if __name__ == "__main__":
    main()
