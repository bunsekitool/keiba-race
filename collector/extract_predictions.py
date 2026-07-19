#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_predictions.py
既存の公開HTML(race_YYYYMMDD.html)から予想スナップショットを抽出し、
data/predictions/YYYYMMDD.json を出力する。

JV-Link には依存しない（どのOSでも動く）。フェーズ1の入口。

使い方:
    python extract_predictions.py path/to/race_20260719.html
    python extract_predictions.py path/to/race_20260719.html --outdir ../data/predictions

出力スキーマは設計書 3.1 に準拠。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

# 競馬場コード(JRA-VAN JyoCD 準拠)。抽出には必須ではないが記録用。
JYO_NAME = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


def _extract_js_var_array(js: str, var_name: str):
    """`const VAR = [ ... ];` の配列リテラルをバランスの取れた括弧で切り出しJSONとして読む。"""
    idx = js.index(var_name)
    start = js.index("[", idx)
    depth = 0
    for k in range(start, len(js)):
        c = js[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(js[start:k + 1])
    raise ValueError(f"{var_name} の配列終端が見つかりません")


def _extract_js_var_string(js: str, var_name: str):
    """`const VAR = "....";` の文字列リテラルを取り出す。"""
    m = re.search(re.escape(var_name) + r"\s*=\s*(\"(?:[^\"\\]|\\.)*\")", js)
    if not m:
        return None
    return json.loads(m.group(1))


def _parse_futan(v):
    """'55.0kg' -> 55.0 / None"""
    if not v:
        return None
    m = re.search(r"[\d.]+", str(v))
    return float(m.group(0)) if m else None


def _parse_age(v):
    """'2歳' -> 2 / None"""
    if not v:
        return None
    m = re.search(r"\d+", str(v))
    return int(m.group(0)) if m else None


def _split_rkey(rkey: str):
    """
    rkey(12桁) = YYYY(4) + JyoCD(2) + Kaiji(2) + Nichiji(2) + RaceNum(2)
    例 '202602011201' -> jyo=02, kaiji=1, nichiji=12, race_num=1
    ※ nichiji の解釈はフェーズ1で JV-Link RaceID と実データ照合して確定する（設計書 4章）。
    """
    rkey = str(rkey)
    if not re.fullmatch(r"\d{12}", rkey):
        return {"jyo": None, "kaiji": None, "nichiji": None, "race_num": None}
    return {
        "jyo": rkey[4:6],
        "kaiji": int(rkey[6:8]),
        "nichiji": int(rkey[8:10]),
        "race_num": int(rkey[10:12]),
    }


def _model_fingerprint(races):
    """
    予想内容の指紋。pf_score の並びから安定ハッシュを作り、モデル版の混在検知に使う。
    (pf_model_daily.txt のハッシュが取れるなら将来そちらへ差し替え)
    """
    h = hashlib.sha1()
    for r in races:
        for horse in r.get("horses", []):
            h.update(f"{r.get('rkey')}:{horse.get('umaban')}:{horse.get('pf_score')}".encode("utf-8"))
    return "pf_fp_" + h.hexdigest()[:12]


def extract(html_path: str):
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    s = html.index("<script>") + len("<script>")
    e = html.index("</script>", s)
    js = html[s:e]

    day_label = _extract_js_var_string(js, "DAY_LABEL")
    day_races = _extract_js_var_array(js, "DAY_RACES")

    # 日付: DAY_LABEL 優先。無ければファイル名 race_YYYYMMDD.html から復元。
    if not day_label:
        m = re.search(r"(\d{4})(\d{2})(\d{2})", os.path.basename(html_path))
        day_label = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

    races_out = []
    for r in day_races:
        rk = str(r.get("rkey"))
        ids = _split_rkey(rk)
        horses_out = []
        for h in r.get("horses", []):
            facts = h.get("facts") or {}
            mq = h.get("market_q")
            horses_out.append({
                "umaban": h.get("umaban"),
                "waku": h.get("waku"),
                "bamei": facts.get("bamei"),
                "pf_rank": h.get("pf_rank"),
                "pf_score": h.get("pf_score"),
                # --- 市場側(公開ページに同梱・発走前オッズ) ---
                "market_q": mq,                       # 正規化市場勝率(1レースで合計1.0)
                "market_rank": h.get("market_rank"),  # 人気順位
                "divergence": h.get("divergence"),    # market_rank - pf_rank(正=モデル高評価)
                "implied_odds": round(1.0 / mq, 2) if mq else None,  # 参考: 市場公正オッズ≒1/q
                # --- 属性 ---
                "kisyu": facts.get("kisyu"),
                "chokyo": facts.get("chokyo"),
                "futan": _parse_futan(facts.get("futan")),
                "age": _parse_age(facts.get("age")),
                "class": facts.get("class"),
            })
        # pf_rank 昇順で安定ソート
        horses_out.sort(key=lambda x: (x["pf_rank"] is None, x["pf_rank"]))
        races_out.append({
            "rkey": rk,
            "jyo": ids["jyo"],
            "jyo_name": JYO_NAME.get(ids["jyo"] or ""),
            "kaiji": ids["kaiji"],
            "nichiji": ids["nichiji"],
            "race_num": ids["race_num"],
            "segment": r.get("segment"),
            "model_status": r.get("model_status"),
            "model_name": r.get("model"),                        # 例 pf_model_daily.txt
            "odds_kind": r.get("odds_kind"),                     # prerace 等
            "agreement_spearman": r.get("agreement_spearman"),  # モデルと市場の一致度
            "has_market": any(h["market_q"] is not None for h in horses_out),
            "horses": horses_out,
        })
    races_out.sort(key=lambda r: (r["jyo"] or "", r["race_num"] or 0))

    model_name = next((r.get("model") for r in day_races if r.get("model")), None)
    return {
        "date": day_label,
        "model_name": model_name,
        "model_version": _model_fingerprint(day_races),
        "captured_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_file": os.path.basename(html_path),
        "num_races": len(races_out),
        "num_horses": sum(len(r["horses"]) for r in races_out),
        "races": races_out,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="公開HTMLから予想スナップショットを抽出")
    ap.add_argument("html", help="race_YYYYMMDD.html のパス")
    ap.add_argument("--outdir", default=None,
                    help="出力ディレクトリ(既定: <スクリプト>/../data/predictions)")
    args = ap.parse_args(argv)

    data = extract(args.html)
    if not data["date"]:
        print("ERROR: 日付を特定できませんでした", file=sys.stderr)
        return 2

    outdir = args.outdir or os.path.join(os.path.dirname(__file__), "..", "data", "predictions")
    os.makedirs(outdir, exist_ok=True)
    ymd = data["date"].replace("-", "")
    outpath = os.path.join(outdir, f"{ymd}.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"OK: {data['date']} races={data['num_races']} horses={data['num_horses']}")
    print(f"    -> {os.path.abspath(outpath)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
