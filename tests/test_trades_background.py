"""MT5 must be hidden repeatedly while it finishes starting. Run with python tests/test_trades_background.py."""
import os
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trades  # noqa: E402

now = [0.0]
proc = Mock(pid=42)
proc.poll.return_value = None

with patch.object(trades.subprocess, "Popen", return_value=proc), \
     patch.object(trades.time, "monotonic", side_effect=lambda: now[0]), \
     patch.object(trades.time, "sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)), \
     patch.object(trades, "hide_terminal") as hide, \
     patch.object(trades, "_lower_priority"):
    trades._launch()

assert hide.call_count >= 80, hide.call_count
assert hide.call_args_list[0].args == (42,)
assert hide.call_args_list[-1].args == (42,)
assert now[0] >= 20
print("OK")
