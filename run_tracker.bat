@echo off
REM ============================================================
REM  勝率トラッカー 日次更新バッチ
REM  使い方:  run_tracker.bat 20260719
REM   1) 予想抽出  2) オッズ抽出  3)(暫定)デモ実績  4) 集計  5) push
REM  ※ このバッチは「公開リポジトリのクローン」直下に置いて実行してください。
REM ============================================================
setlocal
if "%~1"=="" (
  echo 日付を指定してください 例: run_tracker.bat 20260719
  exit /b 1
)
set YMD=%~1

REM --- 作業ラボ側のパス（必要に応じて修正） ---
set LAB=C:\keiba
set JVCACHE=C:\ProgramData\JRA-VAN\Data Lab\cache

echo [1/5] 予想抽出 race_%YMD%.html
python collector\extract_predictions.py "%LAB%\race_%YMD%.html" || goto :err

echo [2/5] オッズ抽出 (JRA-VAN cache)
python collector\parse_jv_o1.py --cache "%JVCACHE%" --date %YMD% || goto :err

echo [3/5] 実績（暫定デモ。着順取得を実装したら fetch_results.py に置換）
python collector\make_demo_results.py data\predictions\%YMD%.json || goto :err

echo [4/5] 集計 -> data\metrics.json
python collector\aggregate.py || goto :err

echo [5/5] Git へ反映
git add dashboard.html data
git commit -m "update tracker %YMD%"
git push

echo 完了: https://bunsekitool.github.io/keiba-race/dashboard.html
exit /b 0

:err
echo エラーが発生しました。中断します。
exit /b 1
