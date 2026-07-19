# 配置とGitアップロード手順

## 結論：どこに置くか

**`C:\keiba`（作業ラボ）はGitに上げません。** ここには `slim4.db`・`ecore_backup_*.db`（合計2GB超）や
zip・監査資料など、公開に不向きで巨大なファイルが大量にあります。GitHub には
**ダッシュボードが必要とする軽いファイルだけ**を、既存の公開リポジトリ
`bunsekitool/keiba-race` に置きます（このリポジトリはすでに GitHub Pages で
`race_YYYYMMDD.html` を配信しているので、同じ場所に dashboard を足すのが最短です）。

推奨レイアウト（公開リポジトリ側）:

```
keiba-race/                     ← GitHubリポジトリ（Pagesで配信中）
├─ index.html                   （既存）
├─ race_20260719.html           （既存・日々更新）
├─ dashboard.html               ★追加：勝率ダッシュボード
├─ .gitignore                   ★追加：DB/zip等を上げない設定
├─ collector/                   ★追加：Pythonスクリプト（配信されないが版管理）
│   ├─ extract_predictions.py
│   ├─ parse_jv_o1.py
│   ├─ aggregate.py
│   └─ make_demo_results.py
└─ data/                        ★追加：ダッシュボードが読む軽量JSON
    ├─ metrics.json
    ├─ predictions/YYYYMMDD.json
    ├─ odds/YYYYMMDD.json
    └─ results/YYYYMMDD.json
```

`C:\keiba` は今まで通り「予想HTMLとオッズを生成するラボ」。スクリプトはラボの
`race_YYYYMMDD.html` と JRA-VAN キャッシュを**入力として読み**、公開リポジトリの
`data\` に**JSONを書き出す**、という役割分担です。

---

## 手順A：GitHub Desktop（GUI・いちばん簡単）

1. GitHub Desktop をインストール → GitHubアカウントでサインイン。
2. `File > Clone repository` で `bunsekitool/keiba-race` を選び、
   保存先を例えば `C:\keiba-site` にしてクローン。
3. 本フォルダの中身（`dashboard.html`, `.gitignore`, `collector\`, `data\`,
   `run_tracker.bat`）を `C:\keiba-site` にコピー。
4. GitHub Desktop に変更が一覧表示される → 下の欄に要約（例：`Add win-rate dashboard`）
   を書いて **Commit to main** → 右上の **Push origin**。
5. 数分後に公開: **https://bunsekitool.github.io/keiba-race/dashboard.html**

## 手順B：コマンドライン（git / gh）

```powershell
# 1) 認証（初回のみ・どちらか）
gh auth login                    # GitHub CLI を使う場合（推奨）
#   もしくは HTTPS + Personal Access Token を使う

# 2) クローン（初回のみ）
git clone https://github.com/bunsekitool/keiba-race.git C:\keiba-site
cd C:\keiba-site

# 3) 本フォルダの中身を C:\keiba-site にコピー
#    dashboard.html / .gitignore / collector\ / data\ / run_tracker.bat

# 4) コミット＆プッシュ
git add dashboard.html .gitignore collector data
git commit -m "Add win-rate tracker dashboard"
git push
```

公開URL: **https://bunsekitool.github.io/keiba-race/dashboard.html**
（GitHub Pages は既に有効。反映まで1〜3分ほど）

---

## 毎日の更新ループ

クローン（`C:\keiba-site`）の直下で、日付を渡して実行するだけ：

```powershell
cd C:\keiba-site
run_tracker.bat 20260719
```

`run_tracker.bat` が「予想抽出 → オッズ抽出 → 実績(暫定デモ) → 集計 → push」まで一括で行います。
バッチ内の `LAB=C:\keiba` と `JVCACHE=...` のパスは環境に合わせて調整してください。

> 着順（結果）の実測取り込みを実装したら、バッチの手順3（デモ実績）を
> `fetch_results.py` に差し替えます。そうすると的中率・回収率・βがすべて実測値になります。

---

## 補足（重要）：着順は `C:\keiba` のDBに既にあるかもしれません

`C:\keiba` に `slim4.db` や `ecore_backup_20260719.db` があります。これらが JV-Data の
蓄積系（レース詳細・馬毎情報）を含むなら、**pywin32/JV-Link を使わずにDBから直接
着順を取れる**可能性が高いです。DBのテーブル構成を確認できれば、`fetch_results.py` を
「DB読み出し版」で実装でき、いちばん手間がかかりません。次はここを見るのがおすすめです。
