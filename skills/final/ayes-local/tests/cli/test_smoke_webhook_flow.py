from scripts import smoke_webhook_flow


def test_build_webhook_payload_contains_expected_fields() -> None:
    payload = smoke_webhook_flow.build_webhook_payload(
        task_id="task_demo",
        summary="库存恢复",
        timestamp=123.0,
        process_name="Safari",
        window_title="商品页",
        priority="medium",
        confidence=0.91,
        event_id="evt_1",
    )

    assert payload["msgtype"] == "text"
    assert "Ayes" in payload["text"]["content"]
    assert "task_demo" in payload["text"]["content"]
    assert "库存恢复" in payload["text"]["content"]


def test_collect_local_webhook_smoke_summary_reports_received_post() -> None:
    summary = smoke_webhook_flow.collect_local_webhook_smoke_summary(
        payload=smoke_webhook_flow.build_webhook_payload(
            task_id="task_demo",
            summary="库存恢复",
            timestamp=123.0,
            process_name="Safari",
            window_title="商品页",
            priority="medium",
            confidence=0.91,
            event_id="evt_1",
        ),
        round_trip_fn=lambda payload: {
            "webhook_url": "http://127.0.0.1:18999/webhook",
            "received": True,
            "request_count": 1,
            "last_path": "/webhook",
            "body": payload,
            "response_status": 200,
            "response_body": '{"ok":true}',
        },
    )

    assert summary["received"] is True
    assert summary["request_count"] == 1
    assert summary["last_path"] == "/webhook"
    assert summary["body"]["msgtype"] == "text"
    assert "库存恢复" in summary["body"]["text"]["content"]


def test_collect_local_webhook_smoke_summary_default_round_trip_receives_post() -> None:
    payload = smoke_webhook_flow.build_webhook_payload(
        task_id="task_demo",
        summary="库存恢复",
        timestamp=123.0,
        process_name="Safari",
        window_title="商品页",
        priority="medium",
        confidence=0.91,
        event_id="evt_1",
    )

    summary = smoke_webhook_flow.collect_local_webhook_smoke_summary(payload=payload)

    assert summary["received"] is True
    assert summary["request_count"] == 1
    assert summary["response_status"] == 200
    assert summary["body"]["msgtype"] == "text"
    assert summary["body"]["text"]["content"] == payload["text"]["content"]
