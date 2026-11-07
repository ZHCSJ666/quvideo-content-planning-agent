"""Build original vector storyboard assets; no downloaded media or raster editing."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def write(name, value):
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    (DATA / "assets").mkdir(parents=True, exist_ok=True)
    write("product.json", {
        "id": "travel-cup", "name": "ROAM 350", "synthetic": True,
        "source": "项目自制演示档案；非真实商品检测数据",
        "claims": {"capacity": "350 ml capacity", "material": "Stainless steel body", "lid": "Screw-top lid", "reuse": "Reusable cup"},
        "unknown": ["thermal retention duration", "leakproof certification", "dishwasher compatibility", "price", "discount", "weight", "durability testing", "environmental impact"],
        "forbidden_claims": ["24 hours", "24 stunden", "leakproof", "auslaufsicher", "BPA-free", "dishwasher-safe", "50%", "guaranteed", "lightweight", "light-weight", "durable", "langlebig", "robust", "sustainable", "nachhaltig", "eco-friendly", "secure", "sicher", "leichtgewicht"],
    })
    write("markets.json", {
        "DE": {"language": "de-DE", "audience": "城市通勤人群（演示设定）", "platform": "竖屏社交短视频（演示渠道）", "format": "9:16 / 20 seconds", "angles": ["随身通勤的容量与使用场景", "办公桌上的重复使用习惯"], "style": "清晰自然的德语；镜头展示具体使用场景；只使用产品档案支持的事实", "cta": "了解产品细节，不编造折扣", "source": "synthetic market brief; not national audience research"},
        "US": {"language": "en-US", "audience": "周末户外与短途出行人群（演示设定）", "platform": "竖屏社交短视频（演示渠道）", "format": "9:16 / 20 seconds", "angles": ["出发前的轻装准备", "短途休息时的使用场景"], "style": "自然美式英语；以具体出行场景开场；避免虚构保温时长与防漏效果", "cta": "Explore product details; no invented offers", "source": "synthetic market brief; not national audience research"},
    })
    write("rules.json", {
        "currency": "simulation_units", "clock": "serial simulated business minutes; not measured wall time",
        "tiers": {"premium": {"cost": 28, "minutes": 240, "description": "更丰富的创意表达；仍须通过相同质量门槛"}, "standard": {"cost": 12, "minutes": 120, "description": "标准脚本与分镜方案"}, "economy": {"cost": 7, "minutes": 60, "description": "复用已选素材，简化表现形式；不削减交付字段"}},
        "tools": {"load_context": [0, 0], "search_assets": [1, 2], "revise_plan": [0, 0], "estimate_cost": [0, 0], "review_content": [1, 5], "save_campaign": [1, 1], "stop": [0, 0]},
        "failure_cost": 2, "failure_minutes": 10, "quality_threshold": 4,
        "max_generation_attempts_per_task": 3,
        "note": "模拟费用覆盖本项目的方案制作流程，不含实际视频制作报价或真实模型账单。相同工具的不同档位是模拟业务服务，不代表模型能力承诺。",
    })
    assets = []
    for aid, title, markets, tags, color in [
        ("cup-hero", "ROAM / PRODUCT", ["DE", "US"], ["product", "capacity", "material"], "#37b7a2"),
        ("cup-detail", "SCREW-TOP / DETAIL", ["DE", "US"], ["lid", "detail", "product"], "#8ea8dc"),
        ("commute", "CITY / COMMUTE", ["DE"], ["commute", "city", "capacity"], "#e2b775"),
        ("desk", "DESK / DAILY", ["DE"], ["desk", "reuse", "office"], "#bc99d4"),
        ("trail", "WEEKEND / TRAIL", ["US"], ["outdoor", "trail", "reuse"], "#a2be81"),
        ("road", "PACK / GO", ["US"], ["travel", "outdoor", "capacity"], "#d69386"),
    ]:
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="540" height="960" viewBox="0 0 540 960"><rect width="540" height="960" fill="#111b27"/><circle cx="410" cy="280" r="220" fill="{color}" opacity=".16"/><path d="M0 760L180 580L380 720L540 520V960H0Z" fill="{color}" opacity=".22"/><rect x="172" y="310" width="196" height="335" rx="36" fill="{color}"/><rect x="163" y="287" width="214" height="62" rx="18" fill="#e9eee9"/><path d="M210 360V590" stroke="white" opacity=".3" stroke-width="10"/><text x="270" y="478" text-anchor="middle" fill="#111b27" font-family="sans-serif" font-size="32">ROAM</text><text x="40" y="90" fill="white" font-family="sans-serif" font-size="22">{title}</text><text x="40" y="866" fill="#b6c4d4" font-family="sans-serif" font-size="16">SYNTHETIC STORYBOARD ASSET</text><text x="40" y="895" fill="#b6c4d4" font-family="sans-serif" font-size="16">{aid} / NOT PRODUCT PHOTOGRAPHY</text></svg>'''
        path = DATA / "assets" / f"{aid}.svg"
        path.write_text(svg)
        assets.append({"id": aid, "path": f"data/assets/{aid}.svg", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "markets": markets, "tags": tags, "aspect_ratio": "9:16", "language": "neutral", "type": "synthetic_vector_still", "description": "平面杯形与旋盖示意、抽象背景和英文场景标签；无真人、无背包、无真实街景、无实拍金属质感。可做裁切、轻推近和字幕叠加，不能假设素材含真实动作或额外场景。", "source": "original programmatic SVG for this project", "rights": "self-created demo asset; no claim to real product photography"})
    write("assets.json", assets)


if __name__ == "__main__":
    main()
