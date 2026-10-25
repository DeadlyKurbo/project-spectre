import archive_status


def test_build_status_embed():
    changelog = {
        "timestamp": "2025-01-01 00:00",
        "update": "Security patch deployed",
        "notes": "Improved clearance validation",
    }
    embed = archive_status.build_status_embed(247, "V3.1.5", 42, changelog, "✅ Operational | No anomalies detected")
    assert embed.title == "📡 Archive System Status"
    text = embed.description
    assert "Total Files: 247" in text
    assert "Current Bot Version: V3.1.5" in text
    assert "Latency / Ping: 42 ms" in text
    assert "[2025-01-01 00:00]" in text
    assert "Update: Security patch deployed" in text
    assert "Notes: Improved clearance validation" in text
    assert "System Health: ✅ Operational | No anomalies detected" in text
