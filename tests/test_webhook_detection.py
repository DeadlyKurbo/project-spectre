from moderation import contains_discord_webhook


def test_webhook_detection():
    assert contains_discord_webhook("https://discord.com/api/webhooks/123/abc")
    assert contains_discord_webhook("check https://discordapp.com/api/webhooks/456/def")
    assert not contains_discord_webhook("no webhooks here")
