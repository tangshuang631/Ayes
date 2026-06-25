from ayes.alerting.notifier import WebhookNotifier
from ayes.config.models import WatchSpec
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability


def test_webhook_notifier_uses_custom_message_template_when_configured() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": True, "queries": ["库存恢复"]},
            "alert": {
                "enabled": True,
                "channel": "wecom_webhook",
                "webhook_url": "http://127.0.0.1:18999/webhook",
                "message_title": "库存提醒",
                "message_template": "任务 {task_id} 命中：{summary} | 优先级 {priority}",
            },
        }
    )
    event = build_event(
        task_id="2026-06-25__stock_watch",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=100.0,
        source="semantic_match",
        event_type="semantic_match",
        priority="high",
        confidence=0.95,
        target=EventTarget(type="process", process_name="Safari", window_title="商品页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="库存恢复，立即购买",
    )

    notifier = WebhookNotifier()

    message = notifier._build_message(event, alert_config=spec.alert)

    assert message.startswith("[Ayes] 库存提醒")
    assert "任务 2026-06-25__stock_watch 命中：库存恢复，立即购买 | 优先级 high" in message
