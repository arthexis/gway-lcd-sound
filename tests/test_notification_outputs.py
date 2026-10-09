"""Shadow output plans remain deterministic and side-effect free."""
import json

from event_engine.notification_rules import Notification
from event_engine.notification_outputs import deliver_shadow, output_plan


def test_output_plan_has_lcd_and_audio_intentions():
    notification = Notification("session-1", "Codex completed", "ok", "codex-turn")
    assert output_plan(notification) == {
        "source": "codex-turn",
        "subject": "session-1",
        "lcd_lines": ("Codex completed", "session-1"),
        "sound": "ok",
    }


def test_shadow_delivery_only_emits_structured_intention(tmp_path):
    messages = []
    notification = Notification("charger-1", "OCPP stop reported", None, "ocpp")
    plan = deliver_shadow(notification, emit=messages.append)
    assert len(messages) == 1
    assert json.loads(messages[0]) == {"mode": "shadow", **json.loads(json.dumps(plan))}
    assert list(tmp_path.iterdir()) == []


def test_shadow_can_be_silent_without_sound():
    plan = output_plan(Notification("session-1", "Codex running", None, "codex-turn"))
    assert plan["sound"] is None
