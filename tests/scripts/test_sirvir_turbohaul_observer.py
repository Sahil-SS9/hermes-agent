import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "sirvir_turbohaul_observer.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("sirvir_turbohaul_observer", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status(*, free_mib, generation_state="idle"):
    return {
        "vram": free_mib,
        "vram_total_mib": [24576] * len(free_mib),
        "generation": {"state": generation_state},
        "active": None,
        "loading": None,
        "grace": None,
        "idle_hot": {"model_tag": "darwin-28b-reason", "remaining_s": 600},
        "queue": {"acceptance_buffer_depth": 0, "staging_queue_depth": 0},
        "parallel_slots": {"used": 0, "max": 1},
    }


def test_uses_turbohaul_vram_as_free_mib_not_used_mib():
    module = load_module()

    snapshot = module.snapshot_from_status(status(free_mib=[23001, 24110]))

    assert snapshot.free_mib == (23001, 24110)
    assert snapshot.minimum_free_gib == 23001 / 1024


def test_requires_two_stable_polls_then_contracts_one_level():
    module = load_module()
    observer = module.Observer(stability_checks=2)
    pressured = module.snapshot_from_status(status(free_mib=[5 * 1024, 20 * 1024]))

    first = observer.evaluate(pressured)
    second = observer.evaluate(pressured)

    assert first["decision"] == "await_stability"
    assert second["current_level"] == 0
    assert second["next_level"] == 1
    assert second["decision"] == "would_hold_context_at_65536"
    assert observer.level == 1


def test_defers_contraction_while_turbohaul_is_generating():
    module = load_module()
    observer = module.Observer(stability_checks=1)
    critical = module.snapshot_from_status(
        status(free_mib=[512, 20 * 1024], generation_state="generating")
    )

    result = observer.evaluate(critical)

    assert result["target_level"] == 5
    assert result["decision"] == "defer_generation_in_flight"
    assert observer.level == 0


def test_recovery_never_requests_context_above_proven_64k_floor():
    module = load_module()
    observer = module.Observer(stability_checks=1)
    observer.level = 1
    recovered = module.snapshot_from_status(status(free_mib=[11 * 1024, 20 * 1024]))

    result = observer.evaluate(recovered)

    assert result["next_level"] == 0
    assert result["decision"] == "would_keep_context_at_65536"
    assert observer.level == 0


def test_observer_source_has_no_lifecycle_or_config_actuators():
    source = MODULE_PATH.read_text()

    for forbidden in ("systemctl", "subprocess", "models.yaml", "config.yaml"):
        assert forbidden not in source
