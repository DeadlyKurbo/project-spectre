from moderation import contains_discord_invite


def test_invite_detection():
    assert contains_discord_invite("join us at https://discord.gg/abc")
    assert contains_discord_invite("https://discord.com/invite/XYZ")
    assert not contains_discord_invite("no links here")
