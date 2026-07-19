@echo off
REM ============================================================
REM  勝率チェック 日次積み上げバッチ（チェック専用・モデルは変更しない）
REM  使い方:
REM     run_tracker.bat            ← 引数なしで「今日」を処理
REM     run_tracker.bat 20260719   ← 日付を指定して処理（過去日の追加も可）
REM  流れ: 予想抽出 → 確定着順/オッズ/三連複払戻(ecore) → 全日集計 → Push
REM  ※ このバッチは公開リポジトリのクローン直下（C:\keiba-site）で実行してください。
REM  ※ レース確定＆EveryDB3で成績取込が済んだ後（夜）に回すと当日分が揃います。
REM ============================================================
setlocal
set YMD=%~1
if "%YMD%"=="" for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set YMD=%%i

REM --- 環境に合わせて調整 ---
set LAB=C:\keiba
set ECORE=%LOCALAPPDATA%\EveryDB3\ecore.db

echo === 勝率チェック %YMD% ===

echo [1/4] 予想抽出  race_%YMD%.html
python collector\extract_predictions.py "%LAB%\race_%YMD%.html" || goto :err

echo [2/4] 確定着順・オッズ・三連複払戻 (ecore.db)
python collector\fetch_results.py --ecore "%ECORE%" --date %YMD% || goto :err

echo [3/4] 集計（蓄積された全日ぶんを再集計）
python collector\aggregate.py || goto :err

echo [4/4] Git へ反映
git add data collector dashboard.html
git commit -m "check data %YMD%"
git push

echo.
echo 完了: https://bunsekitool.github.io/keiba-race/dashboard.html
exit /b 0

:err
echo エラーが発生しました。中断します。
exit /b 1
