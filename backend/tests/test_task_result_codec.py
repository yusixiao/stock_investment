import json


def test_codec_encodes_unicode_and_decodes_json():
    from services.backtest.task_result_codec import TaskResultCodec

    codec = TaskResultCodec()
    encoded = codec.encode({"名称": "测试"})

    assert encoded == '{"名称": "测试"}'
    assert codec.decode(encoded) == {"名称": "测试"}


def test_codec_decodes_empty_or_malformed_json_as_none():
    from services.backtest.task_result_codec import TaskResultCodec

    codec = TaskResultCodec()

    assert codec.decode(None) is None
    assert codec.decode("") is None
    assert codec.decode("not-json") is None


def test_codec_reports_json_null_as_successful_decode():
    from services.backtest.task_result_codec import TaskResultCodec

    codec = TaskResultCodec()

    assert codec.decode_with_status("null") == (True, None)
    assert codec.decode_with_status(None) == (False, None)
    assert codec.decode_with_status("not-json") == (False, None)


def test_codec_builds_scan_summary_and_date_range():
    from services.backtest.task_result_codec import TaskResultCodec

    result = {
        "hits": ["A"],
        "total_scanned": 3,
        "lookback_used": 182,
        "date_range": {"start": "2026-01-01", "end": "2026-08-01"},
    }
    codec = TaskResultCodec()

    assert json.loads(codec.build_summary(result)) == {
        "hit_count": 1,
        "total_scanned": 3,
        "lookback_used": 182,
    }
    assert codec.date_range(result) == ("2026-01-01", "2026-08-01")


def test_codec_builds_full_metrics_summary():
    from services.backtest.task_result_codec import TaskResultCodec

    result = {
        "metrics": {
            "total_return": 0.12,
            "annual_return": 0.2,
            "max_drawdown": -0.08,
            "total_trades": 4,
        }
    }

    assert json.loads(TaskResultCodec().build_summary(result)) == {
        "total_return": 0.12,
        "annual_return": 0.2,
        "max_drawdown": -0.08,
        "total_trades": 4,
    }


def test_codec_builds_screened_symbol_summary():
    from services.backtest.task_result_codec import TaskResultCodec

    assert json.loads(
        TaskResultCodec().build_summary({"screened_symbols": ["A", "B"]})
    ) == {"screened_count": 2}


def test_codec_keeps_empty_summary_and_missing_date_range_compatibility():
    from services.backtest.task_result_codec import TaskResultCodec

    codec = TaskResultCodec()

    assert codec.build_summary({}) == ""
    assert codec.date_range({}) == (None, None)
    assert codec.date_range({"date_range": "invalid"}) == (None, None)
