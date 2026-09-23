"""Самообновление агента видит коммит процесса, а не HEAD папки. python tests/test_agent_update.py

Агент ноутбука работает из папки, где коммитят: после commit+push HEAD уже
равен GitHub, но процесс ещё на старом коде — он обязан перезапуститься.
"""
import os
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402

agent.log.disabled = True      # не писать выдуманные коммиты в настоящий logs/agent.log
head = ["old"]
agent._running_commit = None
with patch.object(agent, "_run_git", lambda *a, **k: head[0]):
    assert agent._local_commit() == "old"      # процесс стартовал на old
    head[0] = "new"                            # в той же папке закоммитили и запушили
    assert agent._local_commit() == "old", "коммит процесса не должен сдвигаться за HEAD"
    with patch.object(agent, "_remote_commit", lambda: "new"), \
         patch.object(agent, "_remote_commit_host", lambda c: socket.gethostname()), \
         patch.object(agent, "_self_update_and_restart") as restart:
        agent.check_for_update(lock=None)
    restart.assert_called_once_with(None, "new")
print("OK")
