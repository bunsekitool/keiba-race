# collector — 勝率管理パイプライン（フェーズ1）

「レース分析器」の予想と実績を突き合わせ、`docs/dashboard.html` 用の
`docs/data/metrics.json` を作るスクリプト群。すべて標準ライブラリのみ・JV-Link COM 非依存。

## 実データで確認できたこと（重要）

- **rkey ↔ JRA-VAN レースID は一致**。O1 レコードのヘッダ RaceID `2026|0719|02|01|12|01` が
  アプリの `rkey=202602011201`（年+場+回+日+R）と完全一致。突合キーの心配は解消。
- **`.rtd` は直接パースできる**。中身は zlib 圧縮 + Shift_JIS の JV-Data レコード。
  `0B31…` は単複枠オッズ＝`O1` レコードで、`parse_jv_o1.py` が
  馬番→単勝オッズ→人気を取り出す。**オッズ取得に pywin32/COM は不要**。
- 抽出したオッズの人気順位はアプリの `market_rank` と **96.5% 一致**
  （不一致は±1のみ＝リアルタイムオッズのスナップショット時刻差。パーサは正しい）。
- ただし**着順（結果）は `.rtd` キャッシュ（速報系）には無い**。`cache/` にあるのは
  オッズ(0B31)のみ。的中率を出すには蓄積系のレース結果（`RA`/`SE` レコード）が必要。

## スクリプト

| ファイル | 役割 | JV-Link |
|---|---|---|
| `extract_predictions.py` | 公開HTML → `data/predictions/YYYYMMDD.json`（予想＋市場q） | 不要 |
| `parse_jv_o1.py` | `.rtd`(O1) → `data/odds/YYYYMMDD.json`（確定単勝オッズ・人気） | 不要 |
| `aggregate.py` | 予想×実績×オッズ → `docs/data/metrics.json`（軸①〜④） | 不要 |
| `make_demo_results.py` | 【デモ】市場qから擬似着順を生成（本番不使用） | 不要 |
| `fetch_results.py` | **未実装**：蓄積系 `RACE`(SE=確定着順) を取得 → `data/results/YYYYMMDD.json` | 要 |

## 使い方（現状）

```bash
# 1) 予想抽出（公開HTMLをDL後）
python extract_predictions.py path/to/race_20260719.html

# 2) オッズ抽出（JRA-VAN cache から）
python parse_jv_o1.py --cache "C:/ProgramData/JRA-VAN/Data Lab/cache" --date 20260719

# 3-demo) 着順が未取得の間、デモ実績で表示確認
python make_demo_results.py ../data/predictions/20260719.json

# 4) 集計
python aggregate.py

# 5) 表示（簡易サーバ経由）
#   docs/ で python -m http.server → dashboard.html を開く
```

## 次の一手：着順の取得（フェーズ2の入口）

的中率・回収率・βを「実測」にするには確定着順が要る。`.rtd`（速報系）には無いので、
**蓄積系データ `RACE`（`SE` レコード＝確定着順、`HR`＝払戻）** を取得する。方式は2択：

1. **pywin32 で JVOpen("RACE", …) → JVRead ループ**（`fetch_results.py` として実装可）。
   32bit Python + JV-Link 必須。SE レコードの `KakuteiJyuni`(確定着順) と馬番で
   `data/results/YYYYMMDD.json` を出力すれば、そのまま `aggregate.py` に流れる。
2. 既存アプリが結果をどこかに保存しているなら、その出力を results スキーマに変換。

results スキーマ（`aggregate.py` が期待する形）:
```json
{ "date":"2026-07-19", "races":[
  { "rkey":"202602011201", "num_runners":8, "horses":[
    { "umaban":5, "bamei":"…", "finish":2, "scratched":false, "win_odds":4.9, "popularity":2 } ]}]}
```
`parse_jv_o1.py` の出力（確定オッズ・人気）を results に合流させれば、回収率が実オッズ化する。
