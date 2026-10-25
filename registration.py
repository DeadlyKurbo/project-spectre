import asyncio
import random
import re
import string

import nextcord
from nextcord import Embed, ButtonStyle, TextInputStyle
from nextcord.ui import View, Button, Modal, TextInput

from constants import ARCHIVE_COLOR, ARCHIVE_EMOJI
from dossier import list_categories
from operator_login import (
    update_id_code,
    list_operators,
    set_password,
    set_clearance,
    detect_clearance,
    detect_rank,
    verify_password,
    generate_session_id,
    get_allowed_categories,
    update_profile,
)


class RegistrationModal(Modal):
    def __init__(self, operator, member: nextcord.Member, session_key: str):
        super().__init__(title="Operator Registration")
        self.operator = operator
        self.member = member
        self.session_key = session_key
        self.password = TextInput(
            label="Set Password",
            style=TextInputStyle.short,
            min_length=6,
            max_length=32,
        )
        self.add_item(self.password)

    async def callback(self, interaction: nextcord.Interaction):
        level = detect_clearance(self.member)
        set_password(self.operator.user_id, self.password.value)
        set_clearance(self.operator.user_id, level)
        rank = detect_rank(self.member)
        desc = (
            "Operator Profile Generated:\n\n"
            f"ID: {self.operator.id_code}\n"
            f"Rank: {rank}\n"
            f"Clearance: Level-{level}\n"
            "Status: ACTIVE\n\n"
            "Your credentials are now stored in the Archive.\n"
            "Proceed to the Archive channel and log in via the terminal.\n\n"
            f"Session Key: {self.session_key}"
        )
        embed = Embed(title="[REGISTRATION COMPLETE]", description=desc, color=ARCHIVE_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class LoginModal(Modal):
    def __init__(self, operator, member: nextcord.Member):
        super().__init__(title="Operator Login")
        self.operator = operator
        self.member = member
        self.password = TextInput(
            label="Password",
            style=TextInputStyle.short,
            min_length=1,
            max_length=32,
        )
        self.add_item(self.password)

    async def callback(self, interaction: nextcord.Interaction):
        success, locked = verify_password(self.operator.user_id, self.password.value)
        if locked:
            await interaction.response.send_message(
                " Account locked. HICOM notified.", ephemeral=True
            )
            return
        if not success:
            await interaction.response.send_message(" Incorrect password.", ephemeral=True)
            return
        session_id = generate_session_id()
        gid = getattr(self.member.guild, "id", None)
        cats = get_allowed_categories(
            self.operator.clearance, list_categories(guild_id=gid)
        )
        from views import CategoryMenu  # local import to avoid circular dependency
        view = CategoryMenu(member=self.member, categories=cats)
        rank = detect_rank(self.member)
        desc = (
            f"Session ID: {session_id}\n\n"
            f"Welcome back, {rank} {self.operator.id_code}.\n"
            f"Clearance Level: {self.operator.clearance} (Secret)\n"
            "Surveillance Status: ACTIVE\n\n"
            "Select a directory to proceed:"
        )
        embed = Embed(
            title=f"{ARCHIVE_EMOJI} [ARCHIVE TERMINAL ACCESS GRANTED]",
            description=desc,
            color=ARCHIVE_COLOR,
        )
        embed.set_footer(text="Glacier Unit-7 Archive Terminal")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ResetPasswordModal(Modal):
    def __init__(self, operator):
        super().__init__(title="Reset Password")
        self.operator = operator
        self.password = TextInput(
            label="New Password",
            style=TextInputStyle.short,
            min_length=6,
            max_length=32,
        )
        self.add_item(self.password)

    async def callback(self, interaction: nextcord.Interaction):
        set_password(self.operator.user_id, self.password.value)
        await interaction.response.send_message(" Password reset.", ephemeral=True)


async def start_registration(
    interaction: nextcord.Interaction, operator, member: nextcord.Member
) -> None:
    session_key = (
        "REG-"
        + f"{random.randint(1000, 9999)}-"
        + "".join(random.choices(string.ascii_uppercase, k=2))
    )
    await interaction.response.send_message(
        "Check your DMs to design your Operator ID.", ephemeral=True
    )
    try:
        message = await member.send("Initializing... [█▒▒▒▒▒▒▒▒▒]")
    except Exception:
        orig = getattr(interaction, "original_message", None)
        if orig:
            message = await orig()
        else:
            class _Dummy:
                async def edit(self, *a, **k):
                    pass

            message = _Dummy()
    await asyncio.sleep(1)
    await message.edit(content="Preparing interface... [████▒▒▒▒▒▒]")
    await asyncio.sleep(1)
    await message.edit(content="Complete. [██████████]")
    await asyncio.sleep(1)
    desc = (
        "Welcome, Operative.\n"
        "Your credentials were not found in the Archive.\n"
        "Follow the steps below to complete your registration:\n\n"
        "Step 1 – Choose Operator ID\n"
        "Reply to this DM with your desired identification number.\n"
        "Requirements: 4-20 characters using letters, numbers, or hyphens.\n"
        "ID must be unique.\n\n"
        "Step 2 – Provide your full name.\n"
        "Step 3 – Report your age.\n"
        "Step 4 – List your specialties.\n"
        "Step 5 – Confirm your occupation or assignment within the unit.\n\n"
        f"Session Key: {session_key}\n"
    )
    embed = Embed(
        title="[PERSONNEL REGISTRATION TERMINAL]",
        description=desc,
        color=ARCHIVE_COLOR,
    )
    await message.edit(content=None, embed=embed)

    channel = getattr(message, "channel", None)
    client = getattr(interaction, "client", None)
    if not channel or not client:
        return

    def check(m: nextcord.Message) -> bool:
        return m.author == member and m.channel == channel

    while True:
        try:
            reply = await client.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            await channel.send(" Registration timed out. Please restart the process.")
            return
        desired = reply.content.strip().upper()
        if not re.match(r"^[A-Z0-9\-]{4,20}$", desired):
            await channel.send(
                "Invalid ID format. Use 4-20 characters with letters, numbers, or hyphens."
            )
            continue
        if any(op.id_code.upper() == desired for op in list_operators()):
            await channel.send("ID already in use. Please try another.")
            continue
        update_id_code(operator.user_id, desired)
        break

    async def prompt_field(prompt_text, validator):
        await channel.send(prompt_text)
        while True:
            try:
                response = await client.wait_for("message", timeout=120, check=check)
            except asyncio.TimeoutError:
                await channel.send(
                    " Registration timed out. Please restart the process."
                )
                return None
            content = response.content.strip()
            valid, error, parsed = validator(content)
            if valid:
                return parsed
            if error:
                await channel.send(error)

    def text_validator(max_length: int, field: str):
        def _validator(value: str):
            if not value:
                return False, f"{field} cannot be blank.", None
            trimmed = value[:max_length]
            return True, None, trimmed

        return _validator

    def age_validator(value: str):
        if not value.isdigit():
            return False, "Age must be a number.", None
        years = int(value)
        if years < 15 or years > 120:
            return False, "Enter an age between 15 and 120.", None
        return True, None, years

    name = await prompt_field("Step 2 – State your full name.", text_validator(80, "Name"))
    if name is None:
        return
    age = await prompt_field("Step 3 – Report your age.", age_validator)
    if age is None:
        return
    specialties = await prompt_field(
        "Step 4 – List your specialties (comma separated is fine).",
        text_validator(200, "Specialties"),
    )
    if specialties is None:
        return
    occupation = await prompt_field(
        "Step 5 – What is your occupation or assignment within the organization?",
        text_validator(120, "Occupation"),
    )
    if occupation is None:
        return

    update_profile(
        operator.user_id,
        name=name,
        age=age,
        specialties=specialties,
        occupation=occupation,
    )

    view = View(timeout=None)
    btn = Button(label="Set Password", style=ButtonStyle.primary)

    async def open_modal(inter: nextcord.Interaction):
        await inter.response.send_modal(
            RegistrationModal(operator, member, session_key)
        )

    btn.callback = open_modal
    view.add_item(btn)
    await channel.send(
        " Operator dossier recorded. Click the button below to finalize registration.",
        view=view,
    )
