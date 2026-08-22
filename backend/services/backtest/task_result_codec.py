import json


class TaskResultCodec:
    def encode(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    def decode(self, value: str | None) -> object | None:
        return self.decode_with_status(value)[1]

    def decode_with_status(self, value: str | None) -> tuple[bool, object | None]:
        if not value:
            return False, None
        try:
            return True, json.loads(value)
        except (TypeError, ValueError):
            return False, None

    def build_summary(self, result: dict) -> str:
        if "hits" in result and "total_scanned" in result:
            return self.encode(
                {
                    "hit_count": len(result.get("hits") or []),
                    "total_scanned": result.get("total_scanned"),
                    "lookback_used": result.get("lookback_used"),
                }
            )
        if "screened_symbols" in result:
            return self.encode({"screened_count": len(result["screened_symbols"])})
        if "metrics" in result:
            metrics = result["metrics"]
            return self.encode(
                {
                    "total_return": metrics.get("total_return"),
                    "annual_return": metrics.get("annual_return"),
                    "max_drawdown": metrics.get("max_drawdown"),
                    "total_trades": metrics.get("total_trades"),
                }
            )
        return ""

    def date_range(self, result: object) -> tuple[str | None, str | None]:
        if not isinstance(result, dict):
            return None, None
        date_range = result.get("date_range")
        if not isinstance(date_range, dict):
            return None, None
        return date_range.get("start"), date_range.get("end")
