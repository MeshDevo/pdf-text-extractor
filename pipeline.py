#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — بايبلاين محلي لاستخراج نص ملفات PDF البحثية إلى TXT.

الفكرة: مجلد دخل، ومجلد خرج، وخط ثابت من خمس مراحل، بلا خادم وبلا إنترنت.
    ضع ملفات PDF في input/  ←  شغّل البايبلاين  ←  تجد ملفات TXT في output/

المراحل الخمس بالترتيب، ولا تبدأ مرحلة قبل اكتمال سابقتها:
    1) intake    — اكتشاف ملفات PDF (ملف واحد أو مجلد كامل، بترتيب أبجدي).
    2) extract   — استخراج النص عبر PyMuPDF مع فصل العمودين.
    3) clean     — تنظيف محافظ: فكّ الكلمات المقطوعة بشرطة، ومسافات نهاية
                   الأسطر، وطيّ الفراغات المتتالية. لا حذف للمحتوى.
    4) write     — كتابة TXT بترميز UTF-8 مع الحفاظ على بنية المجلدات.
    5) report    — manifest.json لكل ملف + pipeline-state.json للاستئناف
                   + ملخص مطبوع في نهاية التشغيل.

الاستئناف: يحفظ البايبلاين بصمة sha256 لكل ملف في pipeline-state.json،
فيتخطى في التشغيل التالي كل ملف لم يتغير. --force يعيد معالجة الكل.

الاستخدام:
    ./run.sh                          # دفعة: كل PDF في input/ إلى output/
    ./run.sh --watch 10               # مراقبة: فحص مجلد الدخل كل 10 ثوانٍ
    python pipeline.py paper.pdf      # ملف واحد إلى output/paper.txt
    python pipeline.py --self-test    # اختبار ذاتي بملفات مولّدة محلياً

الاعتمادية الوحيدة: PyMuPDF (انظر requirements.txt).
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# ثوابت المشروع
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_DIR / "input"
DEFAULT_OUTPUT = PROJECT_DIR / "output"
STATE_FILE = PROJECT_DIR / "pipeline-state.json"
MANIFEST_FILE = "manifest.json"
STATE_VERSION = 1


# ---------------------------------------------------------------------------
# المرحلة 1 — intake: اكتشاف ملفات PDF
# ---------------------------------------------------------------------------

def discover_inputs(input_path: Path) -> list[Path]:
    """يعيد قائمة مرتبة بملفات PDF: ملف واحد كما هو، أو كل PDF في مجلد (تكرارياً)."""
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".pdf" else []
    if input_path.is_dir():
        return sorted(input_path.rglob("*.pdf"))
    return []


def sha256_of(path: Path) -> str:
    """بصمة الملف، بها يعرف البايبلاين إن تغيّر الملف منذ التشغيل السابق."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# المرحلة 2 — extract: استخراج النص مع فصل العمودين
# ---------------------------------------------------------------------------

def extract_page_columns(page) -> str:
    """استخراج صفحة واحدة مع فصل العمودين.

    الكتل في PyMuPDF قد تكون فقرة كاملة (نص لاتيني) أو سطراً واحداً
    (نص صيني غالباً)، فلا يُعتمد ارتفاع الكتلة لتحديد العمودين.
    بدلاً من ذلك: قمة العمودين هي بداية أول تتابع رأسي متقارب من الكتل
    في كل عمود؛ كل ما فوقها رأس (عنوان، ملخص)، وكل ما تحتها تذييل،
    والعمود الأيسر يُقرأ كاملاً ثم الأيمن. والأسطر الملفوفة تُلصق
    داخل العمود الواحد فقط، لا عبر الأعمدة ولا عبر الرأس والتذييل.
    """

    def is_cjk(char: str) -> bool:
        return ("\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff"
                or "\uf900" <= char <= "\ufaff")

    def is_latin_lower(char: str) -> bool:
        return "a" <= char <= "z" or "à" <= char <= "ÿ"

    def join_sep(prev_char: str, next_char: str):
        """الفاصل عند وصل سطرين متتاليين: '' للصينية، ' ' للاتينية
        الصغيرة، None لعدم الوصل (نهاية جملة، عنوان، بداية فقرة...)."""
        if is_cjk(prev_char) and is_cjk(next_char):
            return ""
        if is_latin_lower(prev_char) and is_latin_lower(next_char):
            return " "
        return None

    def join_wrapped_lines(text: str) -> str:
        """وصل الأسطر الملفوفة داخل نص واحد (داخل الكتلة نفسها فقط).

        حرف صيني + سطر + حرف صيني يُلصقان بلا فاصل، وحرف لاتيني
        صغير + سطر + حرف لاتيني صغير يُلصقان بمسافة. النظرة الأمامية
        (?=...) لا تستهلك الحرف التالي، فيلصق re.sub كل الفواصل
        المتتالية — بدونه كان يلصق الأسطر أزواجاً ويترك فاصلاً بين
        كل زوجين (السبب الذي أبقى «对象之/一» مكسورة داخل الكتلة).
        """
        cjk = r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
        text = re.sub(f"({cjk})\n(?={cjk})", r"\1", text)
        text = re.sub(r"([a-zà-ÿ])\n(?=[a-zà-ÿ])", r"\1 ", text)
        return text

    def assemble(group, join_lines: bool) -> str:
        """يجمع كتل مجموعة واحدة مرتبة؛ ويلصق الأسطر المتتابعة داخل العمود فقط.

        الوصل عبر الكتل يشترط ثلاثة أمور: فجوة رأسية صغيرة (≤10 نقاط —
        تباعد أسطر الورقة الصينية 6.3–8.3، وفواصل الحقول/الفقرات ≥10.9؛
        العتبة القديمة 6 كانت ترفض كل الأسطر)، وعدم إزاحة الكتلة التالية
        لليمين (بداية فقرة جديدة تُزاح عادة)، واستمرار الكلمة/الجملة
        (ينتهي السابق ويبدأ التالي بما يدل على ذلك).
        """
        group = sorted(group, key=lambda b: (round(b[1]), b[0]))
        out: list[str] = []
        prev_block = None
        for block in group:
            text = join_wrapped_lines(block[4].strip())
            sep = None
            if join_lines and prev_block is not None and out and text and out[-1]:
                gap = block[1] - prev_block[3]
                if 0 <= gap <= 10 and block[0] <= prev_block[0] + 2:
                    sep = join_sep(out[-1][-1], text[0])
            if sep is not None:
                out[-1] = out[-1] + sep + text
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


def extract_pages(pdf_path: Path) -> tuple[list[str], str]:
    """يستخرج نص كل صفحة على حدة، ويعيد (قائمة الصفحات، اسم المحرك)."""
    try:
        import pymupdf  # الاسم الحديث
    except ImportError:
        import fitz as pymupdf  # الاسم القديم

    pages_text = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pages_text.append(extract_page_columns(page))
    return pages_text, "PyMuPDF"


def extract_pages_fallback(pdf_path: Path) -> tuple[list[str], str]:
    """احتياطي إن غابت PyMuPDF: pypdf (أدق أقل في الأعمدة، لكنه يعمل)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    return [(page.extract_text() or "") for page in reader.pages], "pypdf"


# ---------------------------------------------------------------------------
# المرحلة 3 — clean: تنظيف محافظ للنص
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """تنظيف خفيف فقط: فكّ تقطيع الأسطر بشرطة، ومسافات النهاية، وطيّ الفراغات."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # كلمة مقطوعة بشرطة آخر السطر
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # لا أكثر من سطرين فارغين
    return cleaned.strip() + "\n" if cleaned.strip() else ""


def join_pages(pages: list[str], page_markers: bool) -> str:
    """يدمج صفحات ملف واحد في نص واحد، مع فواصل صفحات اختيارية."""
    parts = []
    for number, page_text in enumerate(pages, start=1):
        cleaned = clean_text(page_text)
        if not cleaned:
            continue
        if page_markers:
            parts.append(f"--- صفحة {number} ---\n\n{cleaned}")
        else:
            parts.append(cleaned)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# المرحلة 4 — write: كتابة TXT
# ---------------------------------------------------------------------------

def output_path_for(pdf_path: Path, input_root: Path, output_root: Path) -> Path:
    """مسار ملف TXT المقابل، مع الحفاظ على بنية المجلدات النسبية."""
    try:
        relative = pdf_path.resolve().relative_to(input_root.resolve())
    except ValueError:
        relative = Path(pdf_path.name)
    return output_root / relative.with_suffix(".txt")


# ---------------------------------------------------------------------------
# المرحلة 5 — report: الحالة والبيان
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """يقرأ pipeline-state.json، أو يعيد حالة فارغة إن لم يوجد بعد."""
    if not STATE_FILE.is_file():
        return {"version": STATE_VERSION, "files": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": STATE_VERSION, "files": {}}


def save_state(state: dict) -> None:
    """يكتب حالة البايبلاين على القرص (بعد كل تشغيل)."""
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def write_manifest(output_root: Path, records: list[dict]) -> Path:
    """يكتب manifest.json في مجلد الخرج: سجل كل ملف عولج في هذا التشغيل."""
    manifest_path = output_root / MANIFEST_FILE
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": records,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest_path


# ---------------------------------------------------------------------------
# الأوركسترا: تشغيل الخط كاملاً على دفعة
# ---------------------------------------------------------------------------

def process_one(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    state: dict,
    force: bool,
    page_markers: bool,
) -> dict:
    """يمرّر ملفاً واحداً عبر المراحل الخمس ويعيد سجله للتقرير."""
    key = str(pdf_path.resolve())
    digest = sha256_of(pdf_path)
    previous = state["files"].get(key, {})
    target = output_path_for(pdf_path, input_root, output_root)

    # البوابة: ملف لم يتغير ومخرجه موجود يُتخطى، إلا بأمر --force.
    if not force and previous.get("sha256") == digest and target.is_file():
        return {**previous, "status": "skipped", "source": key}

    record: dict = {
        "source": key,
        "output": str(target),
        "sha256": digest,
        "engine": None,
        "pages": 0,
        "chars": 0,
        "words": 0,
        "status": "done",
        "warning": None,
    }
    try:
        pages, engine = extract_pages(pdf_path)
    except ImportError:
        pages, engine = extract_pages_fallback(pdf_path)
    except Exception as exc:  # ملف تالف أو محمي مثلاً
        record["status"] = "failed"
        record["warning"] = f"خطأ أثناء الاستخراج: {exc}"
        return record

    record["engine"] = engine
    record["pages"] = len(pages)
    text = join_pages(pages, page_markers)
    if not text.strip():
        record["status"] = "empty"
        record["warning"] = "لا نص قابل للاستخراج؛ قد يكون ممسوحاً ضوئياً ويحتاج OCR."
    record["chars"] = len(text)
    record["words"] = len(text.split())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return record


def run_batch(
    input_path: Path,
    output_root: Path,
    force: bool = False,
    page_markers: bool = False,
) -> dict:
    """تشغيل واحد للدفعة كاملة: اكتشاف ← معالجة كل ملف ← تقرير."""
    input_root = input_path if input_path.is_dir() else input_path.parent
    pdfs = discover_inputs(input_path)
    state = load_state()
    records: list[dict] = []

    for pdf_path in pdfs:
        record = process_one(pdf_path, input_root, output_root, state, force, page_markers)
        records.append(record)
        # تحديث الحالة فوراً بعد كل ملف، فلا يضيع التقدم إن توقف التشغيل.
        state["files"][record["source"]] = record
        save_state(state)
        mark = {"done": "[OK]", "skipped": "[SKIP]", "empty": "[WARN]", "failed": "[FAIL]"}[
            record["status"]
        ]
        print(
            f"{mark} {pdf_path.name} -> {Path(record['output']).name} "
            f"({record['pages']} ص، {record['chars']:,} حرف)"
            + (f" — {record['warning']}" if record["warning"] else "")
        )

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = write_manifest(output_root, records)
    summary = {
        "found": len(pdfs),
        "done": sum(1 for r in records if r["status"] == "done"),
        "skipped": sum(1 for r in records if r["status"] == "skipped"),
        "empty": sum(1 for r in records if r["status"] == "empty"),
        "failed": sum(1 for r in records if r["status"] == "failed"),
        "manifest": str(manifest_path),
    }
    print(
        f"الملخص: وُجد {summary['found']}، أُنجز {summary['done']}، "
        f"تُخطي {summary['skipped']}، فارغ {summary['empty']}، "
        f"فشل {summary['failed']}. البيان: {manifest_path}"
    )
    return summary


# ---------------------------------------------------------------------------
# الاختبار الذاتي: يولّد 3 ملفات محلياً ويتحقق من الخط كاملاً
# ---------------------------------------------------------------------------

def _make_sample_pdfs(input_dir: Path) -> None:
    """يولّد 3 ملفات اختبار: عمودان مع معادلات، وعمود واحد، وصفحة بلا نص."""
    import pymupdf

    two = pymupdf.open()
    page = two.new_page(width=595, height=842)
    page.insert_text((72, 60), "Two Column Paper", fontsize=14)
    page.insert_textbox(
        (72, 90, 280, 400),
        "Introduction. Left column text. Equation: E = m c^2 relates energy and mass.",
        fontsize=10,
    )
    page.insert_textbox(
        (315, 90, 523, 400),
        "Results. Right column text. Second equation: a^2 + b^2 = c^2. End.",
        fontsize=10,
    )
    two.save(input_dir / "two-column.pdf")

    one = pymupdf.open()
    page = one.new_page(width=595, height=842)
    page.insert_text((72, 60), "Single Column Paper", fontsize=14)
    page.insert_textbox(
        (72, 90, 523, 400),
        "This is a plain single column paragraph with no tricks in it.",
        fontsize=10,
    )
    one.save(input_dir / "single-column.pdf")

    blank = pymupdf.open()
    blank.new_page(width=595, height=842)
    blank.save(input_dir / "no-text.pdf")


def self_test() -> int:
    """اختبار ذاتي: يشغّل الخط على ملفات مولّدة ويتحقق من النتائج، ثم ينظّف."""
    import tempfile

    print("الاختبار الذاتي: توليد 3 ملفات PDF في مجلد مؤقت...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        _make_sample_pdfs(input_dir)

        summary = run_batch(input_dir, output_dir)
        assert summary["found"] == 3, summary
        assert summary["done"] == 2, summary  # ملف بلا نص يُحسب فارغاً لا منجزاً
        assert summary["empty"] == 1, summary

        two_text = (output_dir / "two-column.txt").read_text(encoding="utf-8")
        # تطبيع فواصل الأسطر قبل المقارنة: الالتفاف داخل العمود يقسم المعادلة.
        two_norm = " ".join(two_text.split())
        assert two_text.index("Introduction") < two_text.index("Results"), "العمودان اختلطا"
        # آخر سطر من العمود الأيسر يجب أن يأتي قبل أول سطر من الأيمن (يكشف التداخل سطراً بسطر).
        assert two_norm.index("relates energy and mass") < two_text.index("Results"), "العمودان متداخلان"
        assert "E = m c^2" in two_norm and "a^2 + b^2 = c^2" in two_norm
        single_norm = " ".join(
            (output_dir / "single-column.txt").read_text(encoding="utf-8").split()
        )
        assert "plain single column" in single_norm

        # التشغيل الثاني بلا تغييرات يجب أن يتخطى الكل (الاستئناف يعمل).
        summary2 = run_batch(input_dir, output_dir)
        assert summary2["skipped"] == 3, summary2

        # --force يعيد المعالجة فعلاً.
        summary3 = run_batch(input_dir, output_dir, force=True)
        assert summary3["done"] == 2, summary3

    print("SELF-TEST PASSED: الأعمدة صحيحة، والملف الفارغ مُعلَم، والاستئناف يعمل.")
    return 0


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """تحليل المعاملات ثم تشغيل الدفعة مرة، أو المراقبة، أو الاختبار الذاتي."""
    parser = argparse.ArgumentParser(
        description="بايبلاين محلي: PDF من input/ إلى TXT في output/ بخمس مراحل."
    )
    parser.add_argument("input", nargs="?", default=None,
                        help="ملف PDF واحد أو مجلد (الافتراضي: input/ بجانب السكربت)")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="مجلد الخرج (الافتراضي: output/ بجانب السكربت)")
    parser.add_argument("--force", action="store_true", help="إعادة معالجة الكل حتى غير المتغير")
    parser.add_argument("--page-markers", action="store_true",
                        help="إدراج سطر '--- صفحة N ---' بين الصفحات في TXT")
    parser.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                        help="مراقبة مجلد الدخل وإعادة التشغيل كل N ثانية (0 = تشغيل واحد)")
    parser.add_argument("--self-test", action="store_true", help="اختبار ذاتي ثم خروج")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    input_path = Path(args.input) if args.input else DEFAULT_INPUT
    output_root = args.output or DEFAULT_OUTPUT

    if not input_path.exists():
        print(f"خطأ: مسار الدخل غير موجود: {input_path}", file=sys.stderr)
        print("ضع ملفات PDF في input/ أو مرّر المسار: pipeline.py paper.pdf", file=sys.stderr)
        return 1

    if args.watch > 0:
        print(f"مراقبة {input_path} كل {args.watch} ثانية. أوقف بـ Ctrl+C.")
        try:
            while True:
                run_batch(input_path, output_root, args.force, args.page_markers)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("توقفت المراقبة.")
            return 0

    run_batch(input_path, output_root, args.force, args.page_markers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
