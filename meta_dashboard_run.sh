#!/bin/zsh
set -euo pipefail

cd "/Users/parkhyeeun/Library/CloudStorage/Dropbox/코덱스/06-메타 광고 트랜드 분석"

python3 meta_dashboard_pipeline.py init
python3 meta_dashboard_pipeline.py collect --limit-per-category 10
