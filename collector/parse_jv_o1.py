#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_jv_o1.py
JRA-VAN Data Lab のキャッシュ(.rtd)を直接読んで単勝オッズ・人気を抽出する。

判明した事実:
  - .rtd は zlib 圧縮 + Shift_JIS の JV-Data レコード。
  - ファイル名 0B31YYYYMMDDPPKK... の 0B31 は単複枠オッズ。中身は "O1" レコード。
  - O1 ヘッダの RaceID(年+月日+場+回+日+R)は、アプリの rkey(年+場+回+日+R)と一致する。
  => COM/JV-Link を介さずにオッズを取得できる（pywin32 不要）。

注意: これは「オッズ」専用。着順(結果)は O1 には無く、蓄積系の RA/SE レコード
(dataspec "RACE")が別途必要（fetch_results.py 側で扱う）。

使い方:
    # フォルダ内の指定日の 0B31 を集約して odds/YYYYMMDD.json を出力
    python parse_jv_o1.py --cache "C:/ProgramData/JRA-VAN/Data Lab/cache" --date 20260719
    # 単体ファイルの内容を確認
    python parse_jv_o1.py --file 0B31202607190201.rtd --dump
"""
import argparse
import glob
import json
import os
import zlib


def read_record(path: str) -> str:
    raw = open(path, "rb").read()
    data = zlib.decompress(raw)
    try:
        return data.decode("shift_jis")
    except UnicodeDecodeError:
        return data.decode("latin1")


def _num(s):
    s = s.strip()
    return s if s.isdigit() else None


def parse_o1(text: str):
    """O1(単複枠オッズ)レコードから単勝オッズ・人気を取り出す。"""
    if text[:2] != "O1":
        return None
    # ---- 固定長ヘッダ ----
    # 0:2 RecordSpec / 2:3 DataKubun / 3:11 MakeDate(8)
    race = text[11:27]                      # RaceID(16)
    year, monthday = race[0:4], race[4:8]
    jyo, kaiji, nichiji, racenum = race[8:10], race[10:12], race[12:14], race[14:16]
    # 27:35 発表月日時分 / 35:37 登録頭数 / 37:39 出走頭数 / 39:43 各種フラグ
    syusso = int(_num(text[37:39]) or 0)
    rkey = f"{year}{jyo}{kaiji}{nichiji}{racenum}"   # = アプリの rkey

    # ---- 単勝オッズ配列(先頭 出走頭数ぶん) 各8桁: 馬番(2)+オッズ(4,1/10)+人気(2) ----
    horses = []
    base = 43
    for i in range(syusso):
        chunk = text[base + i * 8: base + i * 8 + 8]
        if len(chunk) < 8:
            break
        umaban = _num(chunk[0:2])
        odds_raw = _num(chunk[2:6])          # 例 0017 -> 1.7 / '----'等はNone(取消)
        ninki = _num(chunk[6:8])
        horses.append({
            "umaban": int(umaban) if umaban else None,
            "win_odds": (int(odds_raw) / 10.0) if odds_raw else None,
            "popularity": int(ninki) if ninki else None,
        })
    return {
        "rkey": rkey, "date": f"{year}-{monthday[:2]}-{monthday[2:]}",
        "make_datetime": text[27:35], "syusso": syusso, "horses": horses,
    }


def collect(cache_dir: str, date_yyyymmdd: str):
    files = sorted(glob.glob(os.path.join(cache_dir, f"0B31{date_yyyymmdd}*.rtd")))
    races = []
    for f in files:
        rec = parse_o1(read_record(f))
        if rec:
            races.append(rec)
    # rkey で一意化(最後に読んだ=最新スナップショットを採用)
    by_rkey = {}
    for r in races:
        by_rkey[r["rkey"]] = r
    out = sorted(by_rkey.values(), key=lambda r: r["rkey"])
    return {
        "date": f"{date_yyyymmdd[:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:]}",
        "source": "JV-Data O1 (0B31) cache 直接パース",
        "num_races": len(out),
        "races": out,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="JRA-VAN .rtd(O1)から単勝オッズ抽出")
    ap.add_argument("--cache", help="cache フォルダ")
    ap.add_argument("--date", help="YYYYMMDD")
    ap.add_argument("--file", help="単体 .rtd")
    ap.add_argument("--dump", action="store_true", help="生レコードも表示")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args(argv)

    if args.file:
        rec = parse_o1(read_record(args.file))
        if args.dump:
            print(read_record(args.file)[:120], "...")
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    if not (args.cache and args.date):
        ap.error("--cache と --date、または --file を指定してください")
    data = collect(args.cache, args.date)
    outdir = args.outdir or os.path.join(os.path.dirname(__file__), "..", "data", "odds")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, f"{args.date}.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK: {data['date']} races={data['num_races']} -> {os.path.abspath(outpath)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
