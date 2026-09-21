import threading

import pytest

from screen_translator.tasks import TaskRunner


def test_task_runner_tracks_workers_and_closes():
    runner = TaskRunner()
    started = threading.Event()
    release = threading.Event()

    def work():
        started.set()
        release.wait(2)

    runner.start(work, name="test-worker")
    assert started.wait(1)
    assert runner.active_count == 1
    release.set()
    runner.shutdown(timeout=2)
    assert runner.active_count == 0
    with pytest.raises(RuntimeError):
        runner.start(lambda: None, name="late-worker")
