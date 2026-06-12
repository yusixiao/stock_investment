#!/usr/bin/env bash
# 在修复后的 HK 数据上重跑全部 R 轮次(R1-R12),全部带 _fixed 标记保留旧基准。
# R11 已单独跑过(_fixed),此处跳过。R10/R12 为 H1/H2 子区间。
# 顺序执行,每轮独立日志;全部完成后写 ALL_R_DONE 标记。
set -u
cd /Users/11182300/PycharmProjects/stock_investment

PY=python3
SCRIPT=scripts/run_hk_garp_search.py
H1_START=2010-01-01
H1_END=2018-01-01
H2_START=2018-01-01
H2_END=2026-06-01

run() {
  local round="$1"; shift
  local label="$1"; shift
  echo "===== $(date '+%H:%M:%S') START round=$round label=$label $* ====="
  $PY $SCRIPT --round "$round" --label "$label" "$@"
  echo "===== $(date '+%H:%M:%S') END round=$round label=$label ====="
}

LOG=logs/hk_garp_rerun_all.log
{
  echo "##### RERUN ALL R START $(date) #####"

  # R1-R9 全期
  for r in 1 2 3 4 5 6 7 8 9; do
    run "$r" "_fixed"
  done

  # R10 子区间
  run 10 "_h1_fixed" --start "$H1_START" --end "$H1_END"
  run 10 "_h2_fixed" --start "$H2_START" --end "$H2_END"

  # R11 已单独跑过,跳过

  # R12 子区间
  run 12 "_h1_fixed" --start "$H1_START" --end "$H1_END"
  run 12 "_h2_fixed" --start "$H2_START" --end "$H2_END"

  echo "##### ALL_R_DONE $(date) #####"
} >> "$LOG" 2>&1
