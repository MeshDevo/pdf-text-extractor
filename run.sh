#!/bin/bash
# run.sh — يشغّل بايبلاين PDF المحلي.
# ينشئ بيئة افتراضية ويثبّت الاعتماديات عند أول تشغيل، ثم يمرّر كل المعاملات إلى pipeline.py.
# الاستخدام:
#   ./run.sh                  # دفعة واحدة: input/ ← output/
#   ./run.sh --watch 10       # مراقبة مجلد الدخل كل 10 ثوانٍ
#   ./run.sh paper.pdf        # ملف واحد
#   ./run.sh --self-test      # اختبار ذاتي
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python pipeline.py "$@"
