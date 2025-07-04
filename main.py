import discord
from discord.ext import commands, tasks
from discord import ui, ButtonStyle, Embed
import asyncio
import json
import os
from datetime import datetime
from utils import *
from sochain import check_payment

# Load config
with open('config.json') as f:
    config = json.load(f)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='$', intents=intents)
active_deals = {}

class RoleView(ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=3600)
        self.channel_id = channel_id
        self.user_roles = {}

    @ui.button(label="Sender", style=ButtonStyle.green)
    async def sender_btn(self, interaction, button):
        deal = active_deals[self.channel_id]
        
        # Remove user from any previous role
        for role in ['sender', 'receiver']:
            if deal.get(role) == interaction.user:
                deal[role] = None
        
        # Assign new role
        deal['sender'] = interaction.user
        self.user_roles[interaction.user.id] = 'sender'
        await interaction.channel.send(
            embed=Embed(
                description=f"{interaction.user.mention} selected **Sender** role",
                color=0x000000
            )
        )
        await self.update_interface(interaction)

    @ui.button(label="Receiver", style=ButtonStyle.blurple)
    async def receiver_btn(self, interaction, button):
        deal = active_deals[self.channel_id]
        
        # Remove user from any previous role
        for role in ['sender', 'receiver']:
            if deal.get(role) == interaction.user:
                deal[role] = None
        
        # Assign new role
        deal['receiver'] = interaction.user
        self.user_roles[interaction.user.id] = 'receiver'
        await interaction.channel.send(
            embed=Embed(
                description=f"{interaction.user.mention} selected **Receiver** role",
                color=0x000000
            )
        )
        await self.update_interface(interaction)

    async def update_interface(self, interaction):
        deal = active_deals[self.channel_id]
        
        # Update button states
        for child in self.children:
            if self.user_roles.get(interaction.user.id) == child.label.lower():
                child.style = ButtonStyle.green
                child.disabled = True
            else:
                child.disabled = False
                child.style = ButtonStyle.blurple if child.label == "Receiver" else ButtonStyle.green
        
        # Update embed
        embed = Embed(
            title="Role Selection",
            description="Select your role (one per user):",
            color=0x000000
        )
        embed.add_field(
            name="Sending Litecoin",
            value=deal.get('sender', 'None'),
            inline=False
        )
        embed.add_field(
            name="Receiving Litecoin",
            value=deal.get('receiver', 'None'),
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Proceed if both roles are filled
        if deal.get('sender') and deal.get('receiver'):
            await asyncio.sleep(1)
            await show_role_confirmation(interaction.channel)

async def show_role_confirmation(channel):
    deal = active_deals[channel.id]
    confirm_embed = Embed(
        title="Confirm Roles",
        description="Are these roles correct?",
        color=0x000000
    )
    confirm_embed.add_field(
        name="Sender",
        value=deal['sender'].mention,
        inline=False
    )
    confirm_embed.add_field(
        name="Receiver",
        value=deal['receiver'].mention,
        inline=False
    )
    await channel.send(
        embed=confirm_embed,
        view=ConfirmView("roles", channel.id)
    )

class ConfirmView(ui.View):
    def __init__(self, confirm_type, channel_id):
        super().__init__(timeout=3600)
        self.confirm_type = confirm_type
        self.channel_id = channel_id
        self.confirmed_users = set()

    @ui.button(label="Correct", style=ButtonStyle.green)
    async def correct(self, interaction, button):
        deal = active_deals[self.channel_id]
        if interaction.user.id not in [deal['sender'].id, deal['receiver'].id]:
            return await interaction.response.send_message(
                "❌ Only deal participants can confirm!",
                ephemeral=True
            )
        
        await interaction.channel.send(
            embed=Embed(
                description=f"{interaction.user.mention} responded with **Correct**",
                color=0x000000
            )
        )
        
        self.confirmed_users.add(interaction.user.id)
        
        if len(self.confirmed_users) == 2:
            await interaction.message.edit(
                embed=Embed(
                    title="Confirmation Complete",
                    description="Both parties have confirmed!",
                    color=0x000000
                ),
                view=None
            )
            
            if self.confirm_type == "roles":
                await ask_for_deal_amount(interaction.channel)
            elif self.confirm_type == "amount":
                await show_payment_invoice(interaction.channel)

    @ui.button(label="Incorrect", style=ButtonStyle.red)
    async def incorrect(self, interaction, button):
        deal = active_deals[self.channel_id]
        if interaction.user.id not in [deal['sender'].id, deal['receiver'].id]:
            return await interaction.response.send_message(
                "❌ Only deal participants can confirm!",
                ephemeral=True
            )
        
        await interaction.channel.send(
            embed=Embed(
                description=f"{interaction.user.mention} responded with **Incorrect**",
                color=0x000000
            )
        )
        
        await interaction.message.delete()
        
        if self.confirm_type == "roles":
            deal['sender'] = None
            deal['receiver'] = None
            await interaction.channel.send(
                embed=Embed(
                    title="Roles Reset",
                    description="Please select roles again",
                    color=0x000000
                ),
                view=RoleView(self.channel_id)
            )
        else:
            await ask_for_deal_amount(interaction.channel)

async def ask_for_deal_amount(channel):
    deal = active_deals[channel.id]
    deal['stage'] = 'awaiting_amount'
    
    await channel.send(
        embed=Embed(
            title="Deal Amount",
            description="Please enter the amount in USD (e.g. `10` or `0.5`):",
            color=0x000000
        )
    )

    def check(m):
        try:
            float(m.content)
            return (
                m.channel == channel and 
                m.author == deal['sender']
            )
        except ValueError:
            return False

    try:
        msg = await bot.wait_for('message', check=check, timeout=300)
        usd_amount = float(msg.content)
        ltc_amount = usd_amount / get_live_rate()
        
        deal.update({
            'amount_usd': usd_amount,
            'amount_ltc': ltc_amount,
            'stage': 'amount_confirmation'
        })

        # Send amount confirmation
        confirm_embed = Embed(
            title="Confirm Amount",
            description=f"**${usd_amount:.2f} USD** ≈ `{ltc_amount:.8f} LTC`",
            color=0x000000
        )
        await channel.send(
            embed=confirm_embed,
            view=ConfirmView("amount", channel.id)
        )
        
    except asyncio.TimeoutError:
        await handle_timeout(channel)

async def show_payment_invoice(channel):
    deal = active_deals[channel.id]
    
    invoice_embed = Embed(
        title="Payment Invoice",
        description=(
            f"**Send exactly `{deal['amount_ltc']:.8f} LTC` to:**\n"
            f"`{get_ltc_address()}`\n\n"
            f"`USD Amount:` ${deal['amount_usd']:.2f}\n"
            f"`Exchange Rate:` 1 LTC = ${get_live_rate():.2f}"
        ),
        color=0x000000
    )
    
    await channel.send(
        embed=invoice_embed,
        view=InvoiceButtons()
    )
    
    await channel.send(
        embed=Embed(
            description="Payment invoice has been generated",
            color=0x000000
        )
    )

class InvoiceButtons(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Paste", style=ButtonStyle.green)
    async def paste(self, interaction, button):
        await interaction.response.send_message(
            f"```{get_ltc_address()}```",
            ephemeral=True
        )

    @ui.button(label="Scan QR", style=ButtonStyle.blurple)
    async def qr(self, interaction, button):
        with open('qr.txt') as f:
            qr_path = f.read().strip()
        if os.path.exists(qr_path):
            await interaction.response.send_message(
                file=discord.File(qr_path),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "QR code not found",
                ephemeral=True
            )

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    monitor_payments.start()

@bot.event
async def on_guild_channel_create(channel):
    if channel.category_id == int(config['category_id']):
        await start_deal(channel)

async def start_deal(channel):
    await channel.send(
        f"**{generate_deal_code()}**\n\n"
        "Please send the Developer ID of the user you're dealing with.\n"
        "Type `cancel` to cancel the deal."
    )

    try:
        def check(m):
            return (
                m.channel == channel and 
                m.author != bot.user and
                (m.content.lower() == 'cancel' or m.content.strip().isdigit())
            )
        
        msg = await bot.wait_for('message', check=check, timeout=300)
        
        if msg.content.lower() == 'cancel':
            return await channel.delete()

        try:
            user_id = int(msg.content.strip())
            user = await bot.fetch_user(user_id)
            await channel.set_permissions(user, read_messages=True, send_messages=True)
            await channel.send(
                embed=Embed(
                    description=f"Added {user.mention} to the ticket!",
                    color=0x000000
                )
            )

            welcome_embed = Embed(
                title="Crypto MM",
                description=(
                    "Welcome to our automated cryptocurrency Middleman system!\n"
                    "Your cryptocurrency will be stored securely until the deal is completed.\n\n"
                    "**Created by:** Exploit"
                ),
                color=0x000000
            )
            await channel.send(embed=welcome_embed)

            await channel.send(
                embed=Embed(
                    title="Please Read!",
                    description=(
                        "Please check deal info, confirm your deal and discuss about TOS and warranty.\n"
                        "Ensure all conversations are done within this ticket."
                    ),
                    color=0x000000
                )
            )

            active_deals[channel.id] = {
                'stage': 'roles',
                'start_time': datetime.now(),
                'developer_id': user_id
            }

            role_embed = Embed(
                title="Role Selection",
                description="Select your role:",
                color=0x000000
            )
            role_embed.add_field(
                name="Sending Litecoin",
                value="None",
                inline=False
            )
            role_embed.add_field(
                name="Receiving Litecoin",
                value="None",
                inline=False
            )
            
            await channel.send(
                embed=role_embed,
                view=RoleView(channel.id)
            )
            
        except ValueError:
            await channel.send(
                embed=Embed(
                    description="❌ Invalid Developer ID",
                    color=0x000000
                )
            )
            await channel.delete()

    except asyncio.TimeoutError:
        await handle_timeout(channel)

@tasks.loop(seconds=30)
async def monitor_payments():
    current_time = datetime.now()
    for channel_id, deal in list(active_deals.items()):
        channel = bot.get_channel(channel_id)
        if not channel:
            continue
        
        if deal['stage'] == 'payment':
            payment = check_payment(get_ltc_address(), deal['amount_ltc'])
            if payment:
                await handle_payment_confirmation(channel, payment)
            elif (current_time - deal['start_time']).total_seconds() > config["deal_timeout"]:
                await handle_timeout(channel)

async def handle_payment_confirmation(channel, payment):
    deal = active_deals[channel.id]
    deal['txid'] = payment['txid']
    deal['stage'] = 'awaiting_release'
    
    await channel.send(
        embed=Embed(
            title="✅ Payment Received",
            description=(
                f"**Amount:** {deal['amount_ltc']:.8f} LTC\n"
                f"**TXID:** `{payment['txid']}`\n\n"
                "Please confirm release of funds."
            ),
            color=0x000000
        ),
        view=ReleaseView(channel.id)
    )
    
    await channel.send(
        embed=Embed(
            description="Payment detected on blockchain, awaiting release confirmation",
            color=0x000000
        )
    )

async def handle_timeout(channel):
    await channel.edit(name="⚠️-timeout")
    await channel.send(
        embed=Embed(
            title="Deal Expired",
            description="This deal has timed out due to inactivity.",
            color=0x000000
        )
    )
    await asyncio.sleep(10)
    await channel.delete()
    if channel.id in active_deals:
        del active_deals[channel.id]

class ReleaseView(ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @ui.button(label="Release", style=ButtonStyle.green)
    async def release(self, interaction, button):
        deal = active_deals[self.channel_id]
        if interaction.user not in [deal['sender'], deal['receiver']]:
            return await interaction.response.send_message(
                "❌ Only deal participants can release funds!",
                ephemeral=True
            )
        
        await interaction.response.send_modal(
            AddressModal(self.channel_id)
        )

class AddressModal(ui.Modal):
    def __init__(self, channel_id):
        super().__init__(title="LTC Address Confirmation")
        self.channel_id = channel_id
        self.address = ui.TextInput(
            label="Receiver LTC Address",
            placeholder="ltc1q5anyhzgdnvxf2ed5jxye...",
            min_length=26,
            max_length=48
        )
        self.add_item(self.address)

    async def on_submit(self, interaction):
        if not validate_ltc_address(self.address.value):
            return await interaction.response.send_message(
                "❌ Invalid LTC address format!",
                ephemeral=True
            )
        
        deal = active_deals[self.channel_id]
        deal['receiver_address'] = self.address.value
        
        await interaction.response.send_message(
            embed=Embed(
                title="⚠️ Confirm Address",
                description=f"**Is this address correct?**\n`{self.address.value}`",
                color=0x000000
            ),
            view=ConfirmAddressView(self.channel_id),
            ephemeral=True
        )

class ConfirmAddressView(ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @ui.button(label="Confirm", style=ButtonStyle.green)
    async def confirm(self, interaction, button):
        deal = active_deals[self.channel_id]
        try:
            txid = send_ltc(
                deal['receiver_address'],
                deal['amount_ltc'],
                get_wif_key()
            )
            
            await interaction.channel.send(
                embed=Embed(
                    description=f"{interaction.user.mention} confirmed address",
                    color=0x000000
                )
            )
            
            await interaction.channel.send(
                embed=Embed(
                    title="✅ Litecoin Released",
                    description=(
                        f"**Amount:** {deal['amount_ltc']:.8f} LTC\n"
                        f"**Receiver:** `{deal['receiver_address']}`\n"
                        f"**TXID:** `{txid}`"
                    ),
                    color=0x000000
                )
            )
            await interaction.response.edit_message(
                content="Funds released successfully!",
                embed=None,
                view=None
            )
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Release failed: {str(e)}",
                ephemeral=True
            )

    @ui.button(label="Cancel", style=ButtonStyle.red)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(
            content="Release cancelled",
            embed=None,
            view=None
        )

@bot.command()
@commands.is_owner()
async def release(ctx, receiver_address: str):
    """Owner override to release funds"""
    if ctx.channel.id not in active_deals:
        return await ctx.send("No active deal in this channel!")
    
    deal = active_deals[ctx.channel.id]
    
    if not validate_ltc_address(receiver_address):
        return await ctx.send("❌ Invalid LTC address format!")
    
    try:
        txid = send_ltc(
            receiver_address,
            deal['amount_ltc'],
            get_wif_key()
        )
        
        await ctx.send(
            embed=Embed(
                title="💰 Funds Released (Owner Override)",
                description=(
                    f"**Amount:** {deal['amount_ltc']:.8f} LTC\n"
                    f"**Receiver:** `{receiver_address}`\n"
                    f"**TXID:** `{txid}`"
                ),
                color=0x000000
            )
        )
    except Exception as e:
        await ctx.send(
            embed=Embed(
                title="❌ Release Failed",
                description=str(e),
                color=0x000000
            )
        )

bot.run(config['bot_token'])
