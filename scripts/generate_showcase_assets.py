from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets" / "showcase_fintrace_v1"
ERP_PATH = DATASET / "erp_showcase_fintrace_v1.csv"
VISUAL_DIR = DATASET / "visual_invoices"


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill=(24, 32, 48)) -> None:
    draw.text(xy, str(text), font=font, fill=fill)


def draw_invoice(row: dict, output_path: Path) -> None:
    width, height = 1200, 760
    image = Image.new("RGB", (width, height), "#fbfcff")
    draw = ImageDraw.Draw(image)
    title_font = load_font(42)
    subtitle_font = load_font(22)
    label_font = load_font(24)
    value_font = load_font(26)
    small_font = load_font(19)
    stamp_font = load_font(34)

    red = "#c53030"
    blue = "#1f4f82"
    gray = "#64748b"
    dark = "#172033"

    draw.rectangle((42, 36, width - 42, height - 36), outline=blue, width=3)
    draw.rectangle((64, 62, width - 64, 144), fill="#eef6ff", outline=blue, width=1)
    draw_text(draw, (430, 78), "增值税电子普通发票", title_font, blue)
    draw_text(draw, (78, 102), "FinTrace 模拟票据", subtitle_font, red)
    draw_text(draw, (870, 102), "仅用于产品演示", subtitle_font, red)

    meta = [
        ("发票代码", row.get("invoice_code", "")),
        ("发票号码", row.get("invoice_no", "")),
        ("开票日期", row.get("expense_date", "")),
        ("报销单号", row.get("reimbursement_id", "")),
    ]
    y = 170
    for idx, (label, value) in enumerate(meta):
        x = 82 if idx % 2 == 0 else 650
        if idx % 2 == 0 and idx > 0:
            y += 42
        draw_text(draw, (x, y), f"{label}：", label_font, gray)
        draw_text(draw, (x + 122, y), value, value_font, dark)

    box_top = 282
    draw.rectangle((82, box_top, width - 82, box_top + 132), outline="#d7dde8", width=2)
    draw.line((82, box_top + 66, width - 82, box_top + 66), fill="#d7dde8", width=2)
    draw.line((260, box_top, 260, box_top + 132), fill="#d7dde8", width=2)
    draw.line((760, box_top, 760, box_top + 132), fill="#d7dde8", width=2)
    draw_text(draw, (112, box_top + 22), "购买方", label_font, gray)
    draw_text(draw, (292, box_top + 20), "示例企业（上海）有限公司", value_font, dark)
    draw_text(draw, (792, box_top + 20), f"员工：{row.get('employee_name', '')}", value_font, dark)
    draw_text(draw, (112, box_top + 88), "销售方", label_font, gray)
    draw_text(draw, (292, box_top + 86), row.get("vendor", ""), value_font, dark)
    draw_text(draw, (792, box_top + 86), f"税号：{row.get('vendor_tax_no', '')}", small_font, dark)

    table_top = 452
    headers = ["项目名称", "城市", "规格", "金额", "税额", "价税合计"]
    xs = [82, 360, 510, 690, 850, 1000, width - 82]
    draw.rectangle((82, table_top, width - 82, table_top + 120), outline="#d7dde8", width=2)
    draw.rectangle((82, table_top, width - 82, table_top + 44), fill="#f4f7fb")
    for x in xs[1:-1]:
        draw.line((x, table_top, x, table_top + 120), fill="#d7dde8", width=1)
    for idx, header in enumerate(headers):
        draw_text(draw, (xs[idx] + 16, table_top + 10), header, small_font, gray)

    amount = float(row.get("amount", 0) or 0)
    tax = round(amount * 0.06 / 1.06, 2)
    net = round(amount - tax, 2)
    values = [
        row.get("expense_type", ""),
        row.get("city", ""),
        row.get("description", ""),
        f"{net:.2f}",
        f"{tax:.2f}",
        f"{amount:.2f}",
    ]
    for idx, value in enumerate(values):
        draw_text(draw, (xs[idx] + 16, table_top + 72), value, small_font if idx == 2 else value_font, dark)

    total_y = 604
    draw_text(draw, (82, total_y), "价税合计（小写）：", label_font, gray)
    draw_text(draw, (300, total_y - 4), f"¥ {amount:.2f}", load_font(34), red)
    draw_text(draw, (650, total_y), "费用事由：", label_font, gray)
    draw_text(draw, (770, total_y), row.get("description", ""), value_font, dark)

    draw.rounded_rectangle((824, 668, 1094, 718), radius=10, outline=red, width=3)
    draw_text(draw, (850, 678), "模拟票据 / 非真实发票", small_font, red)
    draw_text(draw, (82, 696), "备注：本票据由 FinTrace 生成，仅用于产品演示和测试，不具备税务效力。", small_font, gray)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def update_manifest(generated_files: list[Path]) -> None:
    manifest_path = DATASET / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["purpose"] = "1-2分钟视频 Showcase 固定演示集，含可视化模拟票据"
    manifest["visual_invoice_dir"] = "visual_invoices"
    manifest["visual_invoice_count"] = len(generated_files)
    manifest["visual_invoice_note"] = "PNG 模拟票据仅用于产品演示，不具备税务效力；OCR 文本仍作为解析兜底。"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    rows = pd.read_csv(ERP_PATH, encoding="utf-8-sig").to_dict(orient="records")
    generated = []
    for row in rows:
        case_id = row["reimbursement_id"]
        output_path = VISUAL_DIR / f"{case_id}_模拟发票.png"
        draw_invoice(row, output_path)
        generated.append(output_path)
    update_manifest(generated)
    print(f"generated {len(generated)} visual invoices in {VISUAL_DIR}")


if __name__ == "__main__":
    main()
