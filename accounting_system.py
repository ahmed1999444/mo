#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import sqlite3
from pathlib import Path

DB_DEFAULT = "sas_luxury.db"

CHART = [
    ("111001", "بنك مسقط 1", "asset"),
    ("111002", "بنك مسقط 2", "asset"),
    ("111003", "بنك نزوى", "asset"),
    ("112000", "الصندوق", "asset"),
    ("113000", "ذمم عملاء عمولات", "asset"),
    ("151000", "أصول ثابتة", "asset"),
    ("152000", "مجمع إهلاك", "asset"),
    ("211000", "ذمم دائنة", "liability"),
    ("212000", "عمولات مؤجلة", "liability"),
    ("213000", "مستحقات رواتب", "liability"),
    ("311000", "رأس المال", "equity"),
    ("312000", "أرباح/خسائر مرحلة", "equity"),
    ("411000", "إيراد عمولات وساطة عقارية", "revenue"),
    ("511000", "رواتب أساسية", "expense"),
    ("513000", "مصروفات ضيافة ومكتبية", "expense"),
    ("517000", "مصروف إهلاك", "expense"),
]

AI_KEYWORDS = {
    "قهوة": "513000",
    "ضيافة": "513000",
    "راتب": "511000",
    "إهلاك": "517000",
}


def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(con: sqlite3.Connection):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
          code TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          category TEXT NOT NULL CHECK(category IN ('asset','liability','equity','revenue','expense')),
          active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS journal_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          entry_no TEXT NOT NULL UNIQUE,
          entry_date TEXT NOT NULL,
          description TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'manual',
          posted_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS journal_lines (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
          account_code TEXT NOT NULL REFERENCES accounts(code),
          debit REAL NOT NULL DEFAULT 0,
          credit REAL NOT NULL DEFAULT 0,
          CHECK (debit >= 0 AND credit >= 0),
          CHECK (NOT (debit = 0 AND credit = 0))
        );
        """
    )
    con.commit()


def seed_chart(con: sqlite3.Connection):
    con.executemany(
        "INSERT OR IGNORE INTO accounts(code,name,category) VALUES(?,?,?)",
        CHART,
    )
    con.commit()


def next_entry_no(con: sqlite3.Connection, date_text: str) -> str:
    year = dt.date.fromisoformat(date_text).year
    prefix = f"JV-{year}-"
    row = con.execute(
        "SELECT entry_no FROM journal_entries WHERE entry_no LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    if not row:
        return prefix + "000001"
    last = int(row["entry_no"].split("-")[-1])
    return prefix + f"{last+1:06d}"


def validate_lines(con: sqlite3.Connection, lines):
    debit = sum(l[1] for l in lines)
    credit = sum(l[2] for l in lines)
    if round(debit, 2) != round(credit, 2):
        raise ValueError(f"القيد غير متوازن: مدين={debit} دائن={credit}")
    for code, _, _ in lines:
        row = con.execute("SELECT active FROM accounts WHERE code=?", (code,)).fetchone()
        if not row:
            raise ValueError(f"الحساب غير موجود: {code}")
        if row["active"] != 1:
            raise ValueError(f"الحساب غير نشط: {code}")


def add_entry(con: sqlite3.Connection, date_text: str, description: str, lines, source="manual"):
    validate_lines(con, lines)
    entry_no = next_entry_no(con, date_text)
    now = dt.datetime.utcnow().isoformat(timespec="seconds")
    cur = con.execute(
        "INSERT INTO journal_entries(entry_no,entry_date,description,source,posted_at) VALUES (?,?,?,?,?)",
        (entry_no, date_text, description, source, now),
    )
    entry_id = cur.lastrowid
    con.executemany(
        "INSERT INTO journal_lines(entry_id,account_code,debit,credit) VALUES(?,?,?,?)",
        [(entry_id, c, d, cr) for c, d, cr in lines],
    )
    con.commit()
    return entry_no


def account_totals(con: sqlite3.Connection):
    q = """
    SELECT a.code, a.name, a.category,
           COALESCE(SUM(l.debit),0) AS debit,
           COALESCE(SUM(l.credit),0) AS credit
    FROM accounts a
    LEFT JOIN journal_lines l ON l.account_code = a.code
    GROUP BY a.code,a.name,a.category
    ORDER BY a.code
    """
    return con.execute(q).fetchall()


def trial_balance(con: sqlite3.Connection):
    rows = account_totals(con)
    out = []
    for r in rows:
        bal = r["debit"] - r["credit"]
        out.append((r["code"], r["name"], round(r["debit"], 3), round(r["credit"], 3), round(bal, 3)))
    return out


def income_statement(con: sqlite3.Connection):
    rows = account_totals(con)
    revenue = sum((r["credit"] - r["debit"]) for r in rows if r["category"] == "revenue")
    expense = sum((r["debit"] - r["credit"]) for r in rows if r["category"] == "expense")
    return round(revenue, 3), round(expense, 3), round(revenue - expense, 3)


def balance_sheet(con: sqlite3.Connection):
    rows = account_totals(con)
    assets = 0.0
    liabilities = 0.0
    equity = 0.0
    for r in rows:
        if r["category"] == "asset":
            assets += (r["debit"] - r["credit"])
        elif r["category"] == "liability":
            liabilities += (r["credit"] - r["debit"])
        elif r["category"] == "equity":
            equity += (r["credit"] - r["debit"])
    _, _, net = income_statement(con)
    equity += net
    return round(assets, 3), round(liabilities, 3), round(equity, 3)


def parse_line(spec: str):
    # code,debit,credit
    code, debit, credit = [x.strip() for x in spec.split(",")]
    return code, float(debit), float(credit)


def import_csv(con: sqlite3.Connection, file_path: str):
    created = 0
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"date", "description", "account", "debit", "credit", "group_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"أعمدة ناقصة في CSV: {','.join(sorted(missing))}")
        grouped = {}
        for row in reader:
            gid = row["group_id"]
            grouped.setdefault(gid, {"date": row["date"], "description": row["description"], "lines": []})
            grouped[gid]["lines"].append(
                (row["account"], float(row["debit"] or 0), float(row["credit"] or 0))
            )
        for g in grouped.values():
            add_entry(con, g["date"], g["description"], g["lines"], source="excel")
            created += 1
    return created


def ai_suggest_account(text: str) -> str:
    for key, account in AI_KEYWORDS.items():
        if key in text:
            return account
    return "513000"


def cmd_init(args):
    con = connect(args.db)
    init_db(con)
    seed_chart(con)
    print("تم إنشاء قاعدة البيانات وتجهيز دليل الحسابات.")


def cmd_add(args):
    con = connect(args.db)
    lines = [parse_line(x) for x in args.line]
    no = add_entry(con, args.date, args.description, lines, source="manual")
    print(f"تم ترحيل القيد تلقائياً: {no}")


def cmd_ai(args):
    con = connect(args.db)
    exp_account = ai_suggest_account(args.text)
    amount = float(args.amount)
    lines = [(exp_account, amount, 0.0), (args.payment_account, 0.0, amount)]
    no = add_entry(con, args.date, args.text, lines, source="ai")
    print(f"AI أنشأ ورحّل القيد: {no} | مصروف={exp_account}")


def cmd_trial(args):
    con = connect(args.db)
    for code, name, d, c, b in trial_balance(con):
        if d or c:
            print(f"{code} | {name:<30} | Dr {d:10.3f} | Cr {c:10.3f} | Bal {b:10.3f}")


def cmd_income(args):
    con = connect(args.db)
    rev, exp, net = income_statement(con)
    print(f"الإيرادات: {rev:.3f}")
    print(f"المصروفات: {exp:.3f}")
    print(f"صافي الربح: {net:.3f}")


def cmd_bs(args):
    con = connect(args.db)
    a, l, e = balance_sheet(con)
    print(f"الأصول: {a:.3f}")
    print(f"الخصوم: {l:.3f}")
    print(f"حقوق الملكية + صافي الفترة: {e:.3f}")
    print(f"فحص التوازن (أصول - خصوم - حقوق ملكية): {a-l-e:.3f}")


def cmd_import(args):
    con = connect(args.db)
    n = import_csv(con, args.file)
    print(f"تم استيراد وترحيل {n} قيد/مجموعة من الملف.")


def build_parser():
    p = argparse.ArgumentParser(description="نظام محاسبي أولي لشركة SAS Luxury")
    p.add_argument("--db", default=DB_DEFAULT)
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("init-db")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add-entry")
    s.add_argument("--date", required=True)
    s.add_argument("--description", required=True)
    s.add_argument("--line", action="append", required=True, help="code,debit,credit")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("ai-entry")
    s.add_argument("--date", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--amount", required=True)
    s.add_argument("--payment-account", default="111001", help="bank/cash account code")
    s.set_defaults(func=cmd_ai)

    s = sub.add_parser("import-csv")
    s.add_argument("--file", required=True)
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("trial-balance")
    s.set_defaults(func=cmd_trial)

    s = sub.add_parser("income-statement")
    s.set_defaults(func=cmd_income)

    s = sub.add_parser("balance-sheet")
    s.set_defaults(func=cmd_bs)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
