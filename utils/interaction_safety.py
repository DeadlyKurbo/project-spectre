import asyncio
import functools
import nextcord
from nextcord import Interaction

class AlreadyResponded(Exception):
    pass

async def ensure_deferred(interaction: Interaction, *, ephemeral: bool = True):
    """
    Zorgt dat de interaction binnen 3s is ge-acknowledged.
    """
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
    except Exception:
        # Als dit faalt, is er meestal al gereageerd
        raise AlreadyResponded()

async def safe_followup(interaction: Interaction, content: str, *, ephemeral: bool = False, embed=None, view=None):
    """
    Stuurt followup of primary response, afhankelijk van status.
    Voorkomt 'application did not respond' & 'interaction already responded'.
    """
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(content, ephemeral=ephemeral, embed=embed, view=view)
        else:
            return await interaction.response.send_message(content, ephemeral=ephemeral, embed=embed, view=view)
    except nextcord.errors.InteractionResponded:
        return await interaction.followup.send(content, ephemeral=ephemeral, embed=embed, view=view)

def auto_ack(fn):
    """
    Decorator: zorgt dat we altijd snel defer'en vóórdat we zware logic draaien.
    Gebruik op button/slash handlers die mogelijk IO doen.
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        # Vind interaction arg
        interaction = None
        for a in args:
            if isinstance(a, Interaction):
                interaction = a
                break
        if interaction is None:
            interaction = kwargs.get("interaction")

        if interaction is None:
            # Ongebruikelijk, maar laat de functie lopen
            return await fn(*args, **kwargs)

        try:
            await ensure_deferred(interaction)
        except AlreadyResponded:
            pass

        return await fn(*args, **kwargs)
    return wrapper
