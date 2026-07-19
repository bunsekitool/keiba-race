#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_results.py
EveryDB3 の ecore.db（JV-Data 蓄積系）から確定着順・確定単勝オッズ・人気を読み出し、
data/results/YYYYMMDD.json を出力する。JV-Link COM / pywin32 は不要。

判明したスキーマ（既存の slim4.py / probe_odds_check.py より）:
  N_RACE      : Year, MonthDay, JyoCD, Kaiji, Nichiji, RaceNum, SyussoTosu, TrackCD, Kyori ...
  N_UMA_RACE  : 同キー + Umaban, KakuteiJyuni(確定着順), Odds(確定単勝, 1/10), Ninki(人気),
                IJyoCD(異常区分 '0'=正常), Bamei(あれば)
  レースキー   : Year+JyoCD+Kaiji+Nichiji+RaceNum（すべてゼロ埋めTEXT）＝アプリの rkey

出力は aggregate.py が読む results スキーマに準拠（"_demo" は付けない＝実測）。

使い方:
  python fetch_results.py --ecore "C:\\Users\\<user>\\AppData\\Local\\EveryDB3\\ecore.db" --date 20260719
  # バックアップDBでも可:
  python fetch_results.py --ecore "C:\\keiba\\ecore_backup_20260719.db" --date 20260719
"""
import argparse
import os
import sqlite3
import sys

DEFAULT_ECORE = os.path.expandvars(r"%LOCALAPPDATA%\EveryDB3\ecore.db")


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)


def _int(x):
    s = str(x).strip() if x is not None else ""
    return int(s) if s.lstrip("-").isdigit() else None


def _cols(con, table):
    try:
        return [r[1] for r in con.execute('PRAGMA table_info("%s")' % table)]
    except sqlite3.Error:
        return []


def fetch(ecore, date_yyyymmdd, jra_only=True):
    y, md = date_yyyymmdd[:4], date_yyyymmdd[4:]
    con = _ro(ecore)

    ur_cols = _cols(con, "N_UMA_RACE")
    if not ur_cols:
        raise SystemExit("ABORT: N_UMA_RACE が見つかりません。ecoreのパスを確認してください。")
    has_bamei = "Bamei" in ur_cols
    has_odds = "Odds" in ur_cols
    has_ninki = "Ninki" in ur_cols

    # 当日のレース一覧（頭数・トラック種別つき）
    rr = _cols(con, "N_RACE")
    track_ok = "TrackCD" in rr
    race_rows = con.execute(
        "SELECT Year,JyoCD,Kaiji,Nichiji,RaceNum,SyussoTosu%s FROM N_RACE "
        "WHERE Year=? AND MonthDay=?" % (",TrackCD" if track_ok else ""),
        (y, md)).fetchall()

    sel = "Umaban,KakuteiJyuni,IJyoCD"
    if has_odds:
        sel += ",Odds"
    if has_ninki:
        sel += ",Ninki"
    if has_bamei:
        sel += ",Bamei"

    races_out = []
    for row in race_rows:
        yy, jyo, kai, nichi, rn = (str(row[i]).strip() for i in range(5))
        syusso = _int(row[5])
        track = _int(row[6]) if track_ok else None
        if jra_only:
            j = _int(jyo)
            if j is None or not (1 <= j <= 10):      # JRA10場のみ（海外・地方を除外）
                continue
            if track is not None and not (10 <= track <= 29):  # 平地のみ
                continue
        rkey = "%s%s%s%s%s" % (yy, jyo, kai, nichi, rn)

        horses = []
        for h in con.execute(
                "SELECT %s FROM N_UMA_RACE "
                "WHERE Year=? AND JyoCD=? AND Kaiji=? AND Nichiji=? AND RaceNum=? "
                "ORDER BY CAST(Umaban AS INTEGER)" % sel,
                (yy, jyo, kai, nichi, rn)):
            d = dict(zip(sel.split(","), h))
            umaban = _int(d.get("Umaban"))
            if umaban is None or umaban < 1 or umaban > 18:
                continue
            ij = str(d.get("IJyoCD") or "0").strip()
            fin = _int(d.get("KakuteiJyuni")) or 0
            scratched = (ij not in ("", "0")) or fin < 1
            odds_raw = str(d.get("Odds") or "").strip() if has_odds else ""
            win_odds = (int(odds_raw) / 10.0) if odds_raw.isdigit() and int(odds_raw) > 0 else None
            horses.append({
                "umaban": umaban,
                "bamei": (str(d.get("Bamei")).strip() if has_bamei and d.get("Bamei") else None),
                "finish": fin if fin >= 1 else None,
                "scratched": scratched,
                "win_odds": win_odds,
                "popularity": _int(d.get("Ninki")) if has_ninki else None,
            })
        if not horses:
            continue
        races_out.append({
            "rkey": rkey,
            "num_runners": syusso if syusso else sum(1 for x in horses if not x["scratched"]),
            "horses": horses,
        })

    races_out.sort(key=lambda r: r["rkey"])
    # 着順が1件も無ければ「まだ確定していない」可能性が高い
    have_finish = sum(1 for r in races_out for h in r["horses"] if h["finish"])
    return {
        "date": "%s-%s-%s" % (y, md[:2], md[2:]),
        "source": "EveryDB3 ecore.db (N_UMA_RACE)",
        "num_races": len(races_out),
        "num_finished_horses": have_finish,
        "races": races_out,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="ecore.db から確定着順・オッズを取得")
    ap.add_argument("--ecore", default=DEFAULT_ECORE, help="ecore.db のパス")
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--all-courses", action="store_true", help="地方・海外も含める")
    args = ap.parse_args(argv)

    if not os.path.exists(args.ecore):
        print("ABORT: ecore が見つかりません: %s" % args.ecore, file=sys.stderr)
        print("  --ecore で正しいパスを指定してください（例: C:\\keiba\\ecore_backup_20260719.db）", file=sys.stderr)
        return 2

    data = fetch(args.ecore, args.date, jra_only=not args.all_courses)
    outdir = args.outdir or os.path.join(os.path.dirname(__file__), "..", "data", "results")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, "%s.json" % args.date)
    import json
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("OK: %s races=%d 着順あり=%d頭 -> %s"
          % (data["date"], data["num_races"], data["num_finished_horses"], os.path.abspath(outpath)))
    if data["num_finished_horses"] == 0:
        print("NOTE: 着順が0件です。まだ結果が未確定か、EveryDB3で当日の蓄積系(成績)が未取込の可能性があります。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
