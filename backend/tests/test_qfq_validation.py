import random
import pandas as pd
import numpy as np
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.qfq_cache import compute_qfq
from config import RAW_KLINE_DIR, DIVIDEND_DIR

BASE_DIR = Path(__file__).resolve().parent.parent.parent
QFQ_VALIDATION_DIR = BASE_DIR / "data" / "kline" / "A" / "qfq_validation"

DATA_AVAILABLE = QFQ_VALIDATION_DIR.exists() and any(QFQ_VALIDATION_DIR.glob("*.parquet"))
skip_no_data = pytest.mark.skipif(not DATA_AVAILABLE, reason="qfq_validation data not available")


def get_random_symbols(n=30):
    files = list(QFQ_VALIDATION_DIR.glob("*.parquet"))
    random.seed(42)
    selected = random.sample(files, min(n, len(files)))
    return [f.stem for f in selected]


@skip_no_data
class TestQfqValidation:
    @pytest.fixture(scope="class")
    def symbols(self):
        return get_random_symbols(50)

    def test_qfq_matches_validation(self, symbols):
        mismatches = []
        for symbol in symbols:
            raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
            div_path = DIVIDEND_DIR / f"{symbol}.parquet"
            val_path = QFQ_VALIDATION_DIR / f"{symbol}.parquet"

            if not raw_path.exists() or not val_path.exists():
                continue

            raw_df = pd.read_parquet(raw_path)
            div_df = pd.read_parquet(div_path) if div_path.exists() else pd.DataFrame()
            val_df = pd.read_parquet(val_path)

            computed = compute_qfq(raw_df, div_df)
            computed_asc = computed.sort_values("date").reset_index(drop=True)
            val_asc = val_df.sort_values("date").reset_index(drop=True)

            common_dates = set(computed_asc["date"]) & set(val_asc["date"])
            if not common_dates:
                continue

            comp_filtered = computed_asc[computed_asc["date"].isin(common_dates)].sort_values("date").reset_index(drop=True)
            val_filtered = val_asc[val_asc["date"].isin(common_dates)].sort_values("date").reset_index(drop=True)

            comp_filtered = comp_filtered[comp_filtered["date"] >= "2010-01-01"].reset_index(drop=True)
            val_filtered = val_filtered[val_filtered["date"] >= "2010-01-01"].reset_index(drop=True)
            if comp_filtered.empty:
                continue

            for col in ["open", "high", "low", "close"]:
                diff = np.abs(comp_filtered[col].values - val_filtered[col].values)
                pct_diff = diff / np.maximum(val_filtered[col].values, 0.01) * 100
                max_pct = pct_diff.max()
                if max_pct > 1.0:
                    bad_idx = np.argmax(pct_diff)
                    bad_date = comp_filtered.iloc[bad_idx]["date"]
                    mismatches.append(f"{symbol} col={col} max_pct={max_pct:.4f}% at {bad_date}")
                    break

        if mismatches:
            msg = f"Mismatches in {len(mismatches)}/{len(symbols)} symbols:\n" + "\n".join(mismatches[:10])
            pytest.fail(msg)
