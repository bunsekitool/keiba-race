#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggregate.py
data/predictions/*.json と data/results/*.json を突合し、
勝率管理ダッシュボード用の集計 docs/data/metrics.json を出力する。

設計:
- 実績(results)が無い日は「予想のみ」の集計（市場との一致度など）だけ出す。
- 実績があれば軸①〜④をすべて算出。
- 依存ライブラリなし（標準ライブラリのみ）。JV-Link 非依存。

軸(設計書5章):
  ① モデル本命(pf_rank==1)の 単勝/複勝/連対 的中率・平均着順・平均人気
  ② モデル vs 市場: 順位相関(ρ)・「割れ」レースでの本命 vs 1番人気 直接対決
  ③ 妙味: divergence(=market_rank-pf_rank) バケット別の的中率・単勝回収率
  ④ 較正: pf_score バンド別の実測勝率 / セグメント別内訳
"""
import argparse
import glob
import json
import os
from collections import defaultdict

SCRATCH_FINISH = {0, None, 99}  # 取消・除外・中止などの着順表現


# ----------------------------- ユーティリティ -----------------------------
def place_cutoff(num_runners: int):
    """複勝圏(何着まで)。JRAルール: 4頭以下は複勝なし / 5-7頭は2着 / 8頭以上は3着。"""
    if num_runners is None or num_runners <= 4:
        return 0  # 複勝対象外
    if num_runners <= 7:
        return 2
    return 3


def spearman(rank_a, rank_b):
    """2つの順位系列のスピアマン順位相関。既に順位(小さいほど上位)前提。タイは平均順位で補正済みとして扱う。"""
    n = len(rank_a)
    if n < 2:
        return None
    ma = sum(rank_a) / n
    mb = sum(rank_b) / n
    cov = sum((a - ma) * (b - mb) for a, b in zip(rank_a, rank_b))
    va = sum((a - ma) ** 2 for a in rank_a)
    vb = sum((b - mb) ** 2 for b in rank_b)
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb) ** 0.5


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def rate(num, den):
    return (num / den) if den else None


# ----------------------------- 読み込み・突合 -----------------------------
def load_json_dir(pattern):
    out = {}
    for p in sorted(glob.glob(pattern)):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        out[d.get("date")] = d
    return out


def join_day(pred, res):
    """
    1日分の予想と実績を突合し、レース単位のレコード列を返す。
    res が None のレースは finish 等を None のまま返す（予想のみ）。
    """
    res_by_rkey = {}
    if res:
        for r in res.get("races", []):
            res_by_rkey[str(r["rkey"])] = r

    joined = []
    warnings = []
    for pr in pred.get("races", []):
        rkey = str(pr["rkey"])
        rr = res_by_rkey.get(rkey)
        r_horses = {}
        num_runners = None
        if rr:
            num_runners = rr.get("num_runners")
            for h in rr.get("horses", []):
                r_horses[h["umaban"]] = h
        horses = []
        for ph in pr["horses"]:
            rh = r_horses.get(ph["umaban"], {})
            # 二次照合: 馬名
            if rh and rh.get("bamei") and ph.get("bamei") and rh["bamei"] != ph["bamei"]:
                warnings.append(f"{rkey} umaban{ph['umaban']} 馬名不一致 pred={ph['bamei']} res={rh.get('bamei')}")
            horses.append({
                **ph,
                "finish": rh.get("finish"),
                "scratched": rh.get("scratched", False),
                "win_odds": rh.get("win_odds"),
                "popularity": rh.get("popularity"),
            })
        joined.append({
            "rkey": rkey, "date": pred.get("date"),
            "jyo": pr.get("jyo"), "jyo_name": pr.get("jyo_name"),
            "segment": pr.get("segment"), "race_num": pr.get("race_num"),
            "agreement_spearman": pr.get("agreement_spearman"),
            "num_runners": num_runners if num_runners else len([h for h in pr["horses"]]),
            "has_result": rr is not None,
            "has_market": pr.get("has_market", any(h.get("market_q") is not None for h in pr["horses"])),
            "horses": horses,
        })
    return joined, warnings


# ----------------------------- 集計本体 -----------------------------
def finished(h):
    return h.get("finish") not in SCRATCH_FINISH and not h.get("scratched")


def aggregate(pred_glob, res_glob):
    preds = load_json_dir(pred_glob)
    results = load_json_dir(res_glob)

    all_races = []
    all_warnings = []
    demo_flag = False
    for date, pred in preds.items():
        res = results.get(date)
        if res and res.get("_demo"):
            demo_flag = True
        joined, warns = join_day(pred, res)
        all_races.extend(joined)
        all_warnings.extend(warns)

    races_with_result = [r for r in all_races if r["has_result"]]

    metrics = {
        "generated_from": {"predictions": pred_glob, "results": res_glob},
        "data_status": {
            "days": sorted(preds.keys()),
            "num_races_total": len(all_races),
            "num_races_with_result": len(races_with_result),
            "results_are_demo": demo_flag,
            "warnings": all_warnings[:50],
        },
        "axis1_honmei": axis1_honmei(races_with_result),
        "axis2_vs_market": axis2_vs_market(races_with_result, all_races),
        "axis3_edge": axis3_edge(races_with_result),
        "axis4_calibration": axis4_calibration(races_with_result),
        "segment_breakdown": segment_breakdown(races_with_result),
        "timeseries": timeseries(all_races),
    }
    return metrics


def axis1_honmei(races):
    """本命(pf_rank==1)の的中率など。"""
    n = 0
    win = place = rentai = 0
    finishes = []
    honmei_market_ranks = []
    # pf上位2/3が複勝圏に1頭でも
    top2_place = top3_place = 0
    for r in races:
        cut = place_cutoff(r["num_runners"])
        honmei = next((h for h in r["horses"] if h.get("pf_rank") == 1 and finished(h)), None)
        if honmei is None:
            continue
        n += 1
        f = honmei["finish"]
        finishes.append(f)
        if honmei.get("market_rank"):
            honmei_market_ranks.append(honmei["market_rank"])
        if f == 1:
            win += 1
        if cut and f <= cut:
            place += 1
        if f <= 2:
            rentai += 1
        # top2/top3
        if cut:
            t2 = [h for h in r["horses"] if h.get("pf_rank") in (1, 2) and finished(h)]
            t3 = [h for h in r["horses"] if h.get("pf_rank") in (1, 2, 3) and finished(h)]
            if any(h["finish"] <= cut for h in t2):
                top2_place += 1
            if any(h["finish"] <= cut for h in t3):
                top3_place += 1
    return {
        "n_races": n,
        "win_rate": rate(win, n),
        "place_rate": rate(place, n),
        "rentai_rate": rate(rentai, n),
        "avg_finish": avg(finishes),
        "honmei_avg_market_rank": avg(honmei_market_ranks),
        "top2_any_place_rate": rate(top2_place, n),
        "top3_any_place_rate": rate(top3_place, n),
    }


def axis2_vs_market(races, all_races):
    """順位相関の平均、および「割れ」レースでの本命 vs 1番人気 直接対決。"""
    rho_model, rho_market = [], []
    split_n = honmei_beats_fav = tie = 0
    agree = [r["agreement_spearman"] for r in all_races if r.get("agreement_spearman") is not None]
    for r in races:
        hs = [h for h in r["horses"] if finished(h) and h.get("pf_rank") and h.get("finish")]
        if len(hs) >= 3:
            pf = [h["pf_rank"] for h in hs]
            fin = [h["finish"] for h in hs]
            rho_model.append(spearman(pf, fin))
            mk = [h["market_rank"] for h in hs if h.get("market_rank")]
            if len(mk) == len(hs):
                rho_market.append(spearman(mk, fin))
        # 割れ: 本命(pf1) と 1番人気(market_rank1)が別馬
        honmei = next((h for h in r["horses"] if h.get("pf_rank") == 1), None)
        fav = next((h for h in r["horses"] if h.get("market_rank") == 1), None)
        if honmei and fav and honmei["umaban"] != fav["umaban"] and finished(honmei) and finished(fav):
            split_n += 1
            if honmei["finish"] < fav["finish"]:
                honmei_beats_fav += 1
            elif honmei["finish"] == fav["finish"]:
                tie += 1
    rm = avg(rho_model)
    rk = avg(rho_market)
    return {
        "mean_rho_model": rm,
        "mean_rho_market": rk,
        "rho_edge": (rm - rk) if (rm is not None and rk is not None) else None,
        "mean_agreement_spearman": avg(agree),
        "split_races": {
            "n": split_n,
            "honmei_beats_favorite": honmei_beats_fav,
            "ties": tie,
            "honmei_win_share": rate(honmei_beats_fav, split_n - tie) if split_n - tie > 0 else None,
        },
    }


def axis3_edge(races):
    """divergence バケット別の 単勝/複勝 的中率・単勝回収率(実オッズ)。"""
    buckets = {"model_high(+2以上)": lambda d: d is not None and d >= 2,
               "model_high(+1)": lambda d: d == 1,
               "neutral(0)": lambda d: d == 0,
               "market_high(-1以下)": lambda d: d is not None and d <= -1}
    out = {}
    for name, cond in buckets.items():
        n = win = place = 0
        staked = returned = 0.0
        has_odds = False
        for r in races:
            cut = place_cutoff(r["num_runners"])
            for h in r["horses"]:
                if not finished(h):
                    continue
                if not cond(h.get("divergence")):
                    continue
                n += 1
                f = h["finish"]
                if f == 1:
                    win += 1
                if cut and f <= cut:
                    place += 1
                # 単勝回収率(確定オッズがあれば実値、無ければ市場公正オッズで近似)
                odds = h.get("win_odds")
                if odds is None and h.get("implied_odds"):
                    odds = h["implied_odds"]  # 近似(発走前・控除前)
                else:
                    if h.get("win_odds") is not None:
                        has_odds = True
                if odds:
                    staked += 100
                    returned += (odds * 100) if f == 1 else 0
        out[name] = {
            "n_horses": n,
            "win_rate": rate(win, n),
            "place_rate": rate(place, n),
            "tansho_roi": rate(returned, staked),
            "roi_uses_confirmed_odds": has_odds,  # False=市場公正オッズ近似
        }
    return out


def axis4_calibration(races, nbins=5):
    """pf_score を分位でバンド分割し、実測勝率/複勝率を出す。"""
    rows = []
    for r in races:
        cut = place_cutoff(r["num_runners"])
        for h in r["horses"]:
            if finished(h) and h.get("pf_score") is not None:
                rows.append((h["pf_score"], h["finish"], cut))
    if not rows:
        return {"bins": []}
    rows.sort(key=lambda x: x[0])
    bins = []
    size = max(1, len(rows) // nbins)
    for i in range(0, len(rows), size):
        chunk = rows[i:i + size]
        if not chunk:
            continue
        wins = sum(1 for s, f, c in chunk if f == 1)
        in3 = sum(1 for s, f, c in chunk if c and f <= c)
        bins.append({
            "score_min": round(chunk[0][0], 4),
            "score_max": round(chunk[-1][0], 4),
            "n": len(chunk),
            "win_rate": rate(wins, len(chunk)),
            "in3_rate": rate(in3, len(chunk)),
        })
    return {"bins": bins}


def segment_breakdown(races):
    """segment / 競馬場 別の本命的中率。"""
    def blank():
        return {"n": 0, "win": 0, "place": 0}
    seg = defaultdict(blank)
    jyo = defaultdict(blank)
    for r in races:
        cut = place_cutoff(r["num_runners"])
        honmei = next((h for h in r["horses"] if h.get("pf_rank") == 1 and finished(h)), None)
        if not honmei:
            continue
        for key, bucket in ((r.get("segment"), seg), (r.get("jyo_name"), jyo)):
            b = bucket[key]
            b["n"] += 1
            if honmei["finish"] == 1:
                b["win"] += 1
            if cut and honmei["finish"] <= cut:
                b["place"] += 1

    def finalize(bucket):
        return [{"key": k, "n": v["n"],
                 "win_rate": rate(v["win"], v["n"]),
                 "place_rate": rate(v["place"], v["n"])}
                for k, v in sorted(bucket.items(), key=lambda kv: -kv[1]["n"])]
    return {"by_segment": finalize(seg), "by_jyo": finalize(jyo)}


def timeseries(all_races):
    """日次の本命単勝/複勝的中率。実績のある日のみ。"""
    by_date = defaultdict(lambda: {"n": 0, "win": 0, "place": 0})
    for r in all_races:
        if not r["has_result"]:
            continue
        cut = place_cutoff(r["num_runners"])
        honmei = next((h for h in r["horses"] if h.get("pf_rank") == 1 and finished(h)), None)
        if not honmei:
            continue
        d = by_date[r["date"]]
        d["n"] += 1
        if honmei["finish"] == 1:
            d["win"] += 1
        if cut and honmei["finish"] <= cut:
            d["place"] += 1
    return [{"date": k, "n": v["n"],
             "win_rate": rate(v["win"], v["n"]),
             "place_rate": rate(v["place"], v["n"])}
            for k, v in sorted(by_date.items())]


def main(argv=None):
    here = os.path.dirname(__file__)
    ap = argparse.ArgumentParser(description="予想×実績を集計しmetrics.jsonを出力")
    ap.add_argument("--pred", default=os.path.join(here, "..", "data", "predictions", "*.json"))
    ap.add_argument("--res", default=os.path.join(here, "..", "data", "results", "*.json"))
    ap.add_argument("--out", default=os.path.join(here, "..", "data", "metrics.json"))
    args = ap.parse_args(argv)

    metrics = aggregate(args.pred, args.res)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    ds = metrics["data_status"]
    print(f"OK: days={ds['days']} races={ds['num_races_total']} with_result={ds['num_races_with_result']} demo={ds['results_are_demo']}")
    print(f"    -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
