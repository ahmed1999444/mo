# SAS Luxury Accounting System (MVP CLI)

هذا **برنامج فعلي أولي** (وليس وثيقة فقط) لتشغيل نظام محاسبي أساسي يرحّل تلقائيًا إلى:
- اليومية
- الأستاذ
- ميزان المراجعة
- قائمة الدخل
- الميزانية العمومية

## المتطلبات
- Python 3.10+

## التشغيل السريع
```bash
python accounting_system.py init-db
python accounting_system.py add-entry --date 2026-02-01 --description "رأس مال" \
  --line 111001,5000,0 --line 311000,0,5000
python accounting_system.py ai-entry --date 2026-02-02 --text "اشتريت قهوة للمكتب" --amount 500 --payment-account 111001
python accounting_system.py trial-balance
python accounting_system.py income-statement
python accounting_system.py balance-sheet
```

## استيراد من CSV (بديل بسيط عن Excel حالياً)
```bash
python accounting_system.py import-csv --file sample_journal.csv
```

تنسيق CSV المطلوب:
- `group_id,date,description,account,debit,credit`
- كل `group_id` يمثل قيدًا واحدًا متعدد السطور.

## ملاحظات
- هذا MVP تقني للتشغيل الفعلي وبداية التطوير.
- المرحلة التالية يمكن تحويله لواجهة مكتبية (Flutter) مع نفس محرك القيود.
