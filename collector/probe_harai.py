#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_harai.py — ecore.db の払戻(HR)テーブルの構造を調べる（読むだけ・評価なし）
三連複の「組番」「払戻金」「人気」列名を特定するための下調べ。

使い方:
  python probe_harai.py --ecore "%LOCALAPPDATA%\\EveryDB3\\ecore.db"
  python probe_harai.py --ecore "C:\\keiba\\ecore_backup_20260719.db"
出力を丸ごと貼ってください。
"""
import argparse, os, re, sqlite3

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ecore", default=os.path.expandvars(r"%LOCALAPPDATA%\EveryDB3\ecore.db"))
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % a.ecore.replace("\\", "/"), uri=True)

    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    pat = re.compile(r"harai|pay|refund|sanren|renpuku|rentan", re.I)
    cand = [t for t in tables if pat.search(t)]
    print("払戻らしきテーブル:", cand or "(見つからず) 全テーブル=%s" % tables)

    for t in cand:
        cols = [d[1] for d in con.execute('PRAGMA table_info("%s")' % t)]
        n = con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        print("\n=== %s (%d行) ===" % (t, n))
        print("列:", cols)
        # 三連複らしき列
        sp = [c for c in cols if re.search(r"sanren.?puku|3.?renpuku|renpuku|fuku3|3fuku", c, re.I)]
        print("三連複らしき列:", sp)
        # サンプル: 2026年の1行を、空でない列だけ表示
        row = con.execute('SELECT * FROM "%s" WHERE Year=\'2026\' LIMIT 1' % t).fetchone()
        if row is None:
            row = con.execute('SELECT * FROM "%s" LIMIT 1' % t).fetchone()
        if row:
            d = dict(zip(cols, row))
            nonempty = {k: v for k, v in d.items() if v not in (None, "", "0", "000000", "0000000000")}
            print("サンプル行(空でない列のみ):")
            for k, v in nonempty.items():
                print("   %-28s = %r" % (k, v))

if __name__ == "__main__":
    raise SystemExit(main())
