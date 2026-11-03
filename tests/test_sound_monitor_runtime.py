"""Contract tests for the extracted event monitor lifecycle (no hardware)."""
from __future__ import annotations

from scripts.gway.sound_engine.monitor_runtime import initial_runtime, run_monitor


def test_initial_runtime_preserves_thermal_baseline_and_alert_bookkeeping():
    assert initial_runtime({"thermal": {"level": "warm"}}, monotonic=123) == {
        "last_thermal_level": "warm",
        "last_thermal_played_level": "warm",
        "last_thermal_at": 123,
        "last_undervoltage_active": False,
        "last_undervoltage_at": 0.0,
    }
    assert initial_runtime({}, monotonic=0)["last_thermal_level"] == "unknown"


def test_runner_observes_baseline_then_one_transition_and_stops():
    observations = iter([{"thermal": {"level": "normal"}}, {"thermal": {"level": "hot"}}])
    writes, events, sleeps, processed = [], [], [], []
    stopping = [False]

    def process(previous, current, runtime, *, dry_run):
        processed.append((previous, current, dict(runtime), dry_run))
        stopping[0] = True

    run_monitor(
        observe=lambda: next(observations),
        process=process,
        persist=writes.append,
        log=lambda name, **fields: events.append((name, fields)),
        should_stop=lambda: stopping[0],
        poll_seconds=0.2,
        dry_run=True,
        sleep=sleeps.append,
        monotonic=lambda: 123.0,
        epoch=lambda: 99.0,
    )
    assert sleeps == [1.0]  # Retain minimum poll interval.
    assert writes[0] == {"started_at": 99.0, "snapshot": {"thermal": {"level": "normal"}}}
    assert writes[1]["snapshot"] == {"thermal": {"level": "hot"}}
    assert processed == [({"thermal": {"level": "normal"}},
                          {"thermal": {"level": "hot"}},
                          initial_runtime({"thermal": {"level": "normal"}}, monotonic=123),
                          True)]
    assert [event for event, _ in events] == ["baseline", "stopped"]


def test_processing_failure_is_logged_and_next_snapshot_becomes_baseline():
    inputs = iter([{"n": 1}, {"n": 2}, {"n": 3}])
    events, saved, seen = [], [], []
    stop = [False]

    def process(previous, current, runtime, *, dry_run):
        seen.append((previous["n"], current["n"]))
        if current["n"] == 2:
            raise RuntimeError("simulated event failure")
        stop[0] = True

    run_monitor(
        observe=lambda: next(inputs),
        process=process,
        persist=saved.append,
        log=lambda name, **fields: events.append((name, fields)),
        should_stop=lambda: stop[0],
        poll_seconds=2.5,
        dry_run=False,
        sleep=lambda _: None,
        monotonic=lambda: 7.0,
        epoch=lambda: 8.0,
    )
    assert seen == [(1, 2), (2, 3)]
    assert saved[-1]["snapshot"] == {"n": 3}
    assert any(event == "error" and "simulated event failure" in fields["error"]
               for event, fields in events)
    assert events[-1][0] == "stopped"


def test_early_stop_preserves_baseline_only():
    reads, saved = [], []

    def observe():
        reads.append(1)
        return {"thermal": {"level": "normal"}}

    run_monitor(
        observe=observe,
        process=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("processed")),
        persist=saved.append,
        log=lambda *args, **kwargs: None,
        should_stop=lambda: True,
        poll_seconds=1,
        dry_run=False,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("slept")),
        monotonic=lambda: 0,
        epoch=lambda: 0,
    )
    assert len(reads) == len(saved) == 1
