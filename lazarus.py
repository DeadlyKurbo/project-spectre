from datetime import datetime, UTC, timedelta
import nextcord
from nextcord.ext import commands, tasks
from constants import GUILD_ID

class LazarusAI(commands.Cog):
    """Minimal hidden AI core running in a single channel.

    The cog maintains a silent background loop (``shadow_loop``) which checks
    for basic health indicators such as a heartbeat and the age of the most
    recent backup.  Status messages are posted to the designated channel and a
    ``/lazarus status`` command exposes the current health summary on demand.
    """

    def __init__(self, bot: commands.Bot, channel_id: int, backup_interval_hours: float, status_interval_minutes: int = 5):
        self.bot = bot
        self.channel_id = channel_id
        self.backup_interval = timedelta(hours=backup_interval_hours)
        self.status_interval_minutes = status_interval_minutes
        self.last_backup_ts = datetime.now(UTC)
        self.last_heartbeat = datetime.now(UTC)
        self.shadow_loop.change_interval(minutes=status_interval_minutes)

    def start(self) -> None:
        """Start the shadow monitoring loop."""
        if not self.shadow_loop.is_running():
            self.shadow_loop.start()

    def note_backup(self, ts: datetime | None = None) -> None:
        """Record that a backup completed at ``ts`` (or ``now``)."""
        self.last_backup_ts = ts or datetime.now(UTC)

    def compute_status(self, now: datetime | None = None) -> str:
        """Return a short human readable health summary."""
        now = now or datetime.now(UTC)
        if now - self.last_heartbeat > timedelta(minutes=self.status_interval_minutes * 2):
            return "Heartbeat stalled"
        if now - self.last_backup_ts > self.backup_interval:
            return "Backup outdated"
        return "System Check: OK"

    @tasks.loop(minutes=1)
    async def shadow_loop(self) -> None:
        """Background loop that posts status updates periodically."""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(self.compute_status())
        self.last_heartbeat = datetime.now(UTC)

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != self.channel_id:
            return
        await message.channel.send(self.compute_status())

    @nextcord.slash_command(name="lazarus", description="Lazarus AI controls", guild_ids=[GUILD_ID])
    async def lazarus_root(self, interaction: nextcord.Interaction):
        pass

    @lazarus_root.subcommand(name="status", description="Show Lazarus status")
    async def lazarus_status(self, interaction: nextcord.Interaction):
        if interaction.channel.id != self.channel_id:
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return
        await interaction.response.send_message(self.compute_status())
