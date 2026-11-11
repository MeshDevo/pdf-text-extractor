#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf2txt.py — استخراج النص الكامل من ملف PDF بحثي إلى ملف TXT (UTF-8).

الاستخدام (خطوتان فقط):
    1) python pdf2txt.py paper.pdf
    2) يُنشأ paper.txt بجانب الملف تلقائياً.

مع تحديد اسم ملف الإخراج:
    python pdf2txt.py paper.pdf -o output.txt

الاعتمادية الوحيدة: PyMuPDF (تُستورد باسم fitz)
    pip install PyMuPDF

لماذا PyMuPDF؟
    - أسرع وأدق من PyPDF2 في ملفات الأبحاث الشائعة.
    - يعيد ترتيب كتل النص ويفصل العمودين (يساراً ثم يميناً) فلا
      تختلط أسطر العمودين، بخلاف الاستخراج الخام.
    - يحافظ على النص المحيط بالمعادلات الرياضية كما هو في طبقة النص،
      لأن المعادلات نفسها في ملفات PDF البحثية غالباً نصوص/رموز لا صور.

ملاحظة عن الحدود:
    - إن كان ملف PDF ممسوحاً ضوئياً بلا طبقة نص (صور فقط)، فلن يجد
      السكربت نصاً ليستخرجه. عندها يلزم OCR (مثل ocrmypdf أو Tesseract)
      قبل هذه الخطوة، وهذا خارج نطاق هذه الأداة الخفيفة.
    - لا يستخرج الصور ولا الجداول كجداول ولا ينظّم المراجع؛ نص عادي فقط.
"""

import argparse
import re
import sys
from pathlib import Path


def clean_text(text: str) -> str:
    """تنظيف خفيف: إزالة مسافات نهاية الأسطر وطيّ الفراغات المتتالية."""
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = "\n".join(lines)
    # لا أكثر من سطرين فارغين متتاليين
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def extract_page_columns(page) -> str:
    """استخراج صفحة واحدة مع فصل العمودين.

    الكتل في PyMuPDF قد تكون فقرة كاملة (نص لاتيني) أو سطراً واحداً
    (نص صيني غالباً)، فلا يُعتمد ارتفاع الكتلة لتحديد العمودين.
    بدلاً من ذلك: قمة العمودين هي بداية أول تتابع رأسي متقارب من الكتل
    في كل عمود؛ كل ما فوقها رأس (عنوان، ملخص)، وكل ما تحتها تذييل،
    والعمود الأيسر يُقرأ كاملاً ثم الأيمن. والأسطر الصينية الملفوفة
    تُلصق داخل العمود الواحد فقط، لا عبر حدود الكتل.
    """

    def is_cjk(char: str) -> bool:
        return ("\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff"
                or "\uf900" <= char <= "\ufaff")

    def join_wrapped_lines(text: str) -> str:
        """وصل الأسطر الملفوفة داخل نص واحد: حرف صيني + سطر + حرف صيني."""
        cjk = r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
        return re.sub(f"({cjk})\n({cjk})", r"\1\2", text)

    def assemble(group, join_lines: bool) -> str:
        """يجمع كتل مجموعة واحدة مرتبة؛ ويلصق الأسطر الصينية المتتابعة داخل العمود فقط."""
        group = sorted(group, key=lambda b: (round(b[1]), b[0]))
        out: list[str] = []
        prev_block = None
        for block in group:
            text = join_wrapped_lines(block[4].strip())
            if (join_lines and prev_block is not None and out
                    and 0 <= (block[1] - prev_block[3]) <= 6
                    and out[-1] and is_cjk(out[-1][-1]) and text and is_cjk(text[0])):
                out[-1] = out[-1] + text
            else:
                out.append(text)
            prev_block = block
        return "\n".join(out)

    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not blocks:
        return ""
    if len(blocks) == 1:
        return join_wrapped_lines(blocks[0][4])

    width = page.rect.width
    mid = width / 2.0

    def in_left(block) -> bool:
        return block[2] <= mid + 10

    def in_right(block) -> bool:
        return block[0] >= mid - 10

    def column_top(column_blocks) -> float:
        """أعلى تتابع رأسي في العمود: أول كتلة تليها أخرى بفارق سطر واحد."""
        ordered = sorted(column_blocks, key=lambda b: (round(b[1]), b[0]))
        for i, block in enumerate(ordered):
            if i + 1 < len(ordered) and 0 <= (ordered[i + 1][1] - block[1]) <= 25:
                return block[1]
        return ordered[0][1]

    def column_bottom(column_blocks) -> float:
        """أسفل آخر تتابع رأسي في العمود."""
        ordered = sorted(column_blocks, key=lambda b: (round(b[1]), b[0]))
        for i in range(len(ordered) - 1, 0, -1):
            if 0 <= (ordered[i][1] - ordered[i - 1][1]) <= 25:
                return ordered[i][3]
        return ordered[-1][3]

    left_all = sorted([b for b in blocks if in_left(b)], key=lambda b: (round(b[1]), b[0]))
    right_all = sorted([b for b in blocks if in_right(b)], key=lambda b: (round(b[1]), b[0]))

    if not left_all or not right_all:
        # عمود واحد فعلاً: الترتيب الطبيعي من الأعلى للأسفل.
        return assemble(blocks, join_lines=True)

    top_y = min(column_top(left_all), column_top(right_all))
    bottom_y = max(column_bottom(left_all), column_bottom(right_all))
    header, footer, left, right, middle = [], [], [], [], []
    for block in blocks:
        if block[3] <= top_y + 1:
            header.append(block)
        elif block[1] >= bottom_y - 1:
            footer.append(block)
        elif in_left(block):
            left.append(block)
        elif in_right(block):
            right.append(block)
        else:
            middle.append(block)

    parts = [
        assemble(header, join_lines=False),
        assemble(left, join_lines=True),
        assemble(right, join_lines=True),
        assemble(middle, join_lines=False),
        assemble(footer, join_lines=False),
    ]
    return "\n".join(part for part in parts if part)


def extract_with_pymupdf(pdf_path: Path) -> list[str]:
    """الاستخراج الأساسي عبر PyMuPDF مع فصل الأعمدة."""
    try:
        import pymupdf  # الاسم الحديث
    except ImportError:
        import fitz as pymupdf  # الاسم القديم

    pages_text = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pages_text.append(extract_page_columns(page))
    return pages_text


def extract_with_pypdf(pdf_path: Path) -> list[str]:
    """احتياطي إن لم تكن PyMuPDF مثبّتة: pypdf (أو PyPDF2)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    return [(page.extract_text() or "") for page in reader.pages]


def extract_text(pdf_path: Path) -> tuple[str, str]:
    """يعيد (النص الكامل، اسم المحرك المستخدَم)."""
    try:
        pages = extract_with_pymupdf(pdf_path)
        engine = "PyMuPDF"
    except ImportError:
        pages = extract_with_pypdf(pdf_path)
        engine = "pypdf"
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    return clean_text(text), engine


def main(argv: list[str] | None = None) -> int:
    """نقطة الدخول: تحليل المعاملات ثم الاستخراج ثم الحفظ."""
    parser = argparse.ArgumentParser(
        description="استخراج النص الكامل من PDF بحثي إلى TXT (UTF-8)."
    )
    parser.add_argument("pdf", type=Path, help="ملف PDF المدخَل")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="ملف TXT الناتج (الافتراضي: نفس اسم PDF بامتداد .txt)",
    )
    args = parser.parse_args(argv)

    if not args.pdf.is_file():
        print(f"خطأ: الملف غير موجود: {args.pdf}", file=sys.stderr)
        return 1
    if args.pdf.suffix.lower() != ".pdf":
        print(f"تحذير: الملف ليس بامتداد .pdf: {args.pdf}", file=sys.stderr)

    output = args.output or args.pdf.with_suffix(".txt")

    try:
        text, engine = extract_text(args.pdf)
    except Exception as exc:  # ملف تالف أو محمي مثلاً
        print(f"خطأ أثناء الاستخراج ({exc})", file=sys.stderr)
        return 1

    if not text.strip():
        print(
            "تحذير: لم يُعثَر على نص قابل للاستخراج. "
            "قد يكون الملف ممسوحاً ضوئياً (صور فقط) ويحتاج OCR أولاً.",
            file=sys.stderr,
        )

    output.write_text(text, encoding="utf-8")
    print(f"المحرك: {engine}")
    print(f"الحروف المستخرجة: {len(text):,}")
    print(f"حُفظ في: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
