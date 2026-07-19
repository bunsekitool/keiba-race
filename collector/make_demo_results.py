#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_demo_results.py  【デモ専用・本番では使わない】

JV-Link 接続前にダッシュボードの動作を確認するため、予想JSONの market_q(市場勝率)を
使って着順・確定オッズを確率的に生成し data/results/YYYYMMDD.json を作る。
出力には "_demo": true を付与し、集計側・ダッシュボードで「デモ」バナーを出せるようにする。

本番では fetch_results.py(JV-Link)が同じスキーマの results/YYYYMMDD.json を出力する。

使い方:
    python make_demo_results.py ../data/predictions/20260719.json
"""
import argparse
import json
import os
import random

TAKEOUT = 0.20  # 単勝控除率(概算)。デモの確定オッズ生成に使用。


def plackett_luce_order(horses, rng):
    """market_q を強度としたPlackett-Luceで着順(1..n)を生成。人気馬ほど上位に来やすい。"""
    pool = list(horses)
    order = []
    while pool:
        weights = [max(h.get("market_q") or 1e-6, 1e-6) for h in pool]
        total = sum(weights)
        pick = rng.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if pick <= acc:
                order.append(pool.pop(i))
                break
        else:
            order.append(pool.pop())
    return order  # 先頭が1着


def make(pred_path, seed=20260719):
    with open(pred_path, encoding="utf-8") as f:
        pred = json.load(f)
    rng = random.Random(seed)

    races_out = []
    for r in pred["races"]:
        horses = r["horses"]
        order = plackett_luce_order(horses, rng)
        finish_by_umaban = {h["umaban"]: i + 1 for i, h in enumerate(order)}
        hs = []
        for h in horses:
            q = h.get("market_q")
            # 確定オッズ≒(1-控除)/q に小さなノイズ。無ければNone。
            if q:
                odds = round(max(1.0, (1 - TAKEOUT) / q) * rng.uniform(0.9, 1.15), 1)
            else:
                odds = None
            hs.append({
                "umaban": h["umaban"],
                "bamei": h.get("bamei"),
                "finish": finish_by_umaban[h["umaban"]],
                "scratched": False,
                "win_odds": odds,
                "popularity": h.get("market_rank"),
            })
        # デモ用 三連複払戻: 当たり=1〜3着、Pay≒市場勝率の積から概算
        podium = sorted(order[:3], key=lambda h: h["umaban"])
        qs = [max(h.get("market_q") or 0.05, 0.01) for h in podium]
        prod = qs[0] * qs[1] * qs[2]
        pay = int(min(99999, max(100, round(0.65 / prod / 10.0) * 10)))
        races_out.append({
            "rkey": r["rkey"],
            "num_runners": len(horses),
            "track_cond": "良", "weather": "晴",
            "sanrenpuku": [{"kumi": [h["umaban"] for h in podium], "pay": pay}],
            "horses": hs,
        })

    return {
        "date": pred["date"],
        "_demo": True,
        "note": "デモ生成(market_qベース)。本番はJV-Link出力に置換。",
        "races": races_out,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="[デモ] 予想JSONから擬似実績を生成")
    ap.add_argument("pred", help="predictions/YYYYMMDD.json")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args(argv)
    data = make(args.pred)
    outdir = args.outdir or os.path.join(os.path.dirname(args.pred), "..", "results")
    os.makedirs(outdir, exist_ok=True)
    ymd = data["date"].replace("-", "")
    outpath = os.path.join(outdir, f"{ymd}.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK[DEMO]: {data['date']} races={len(data['races'])} -> {os.path.abspath(outpath)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
