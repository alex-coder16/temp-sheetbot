"""
Copyright (c) 2024 X Developments

This software is a Discord bot developed for fetching music data from the Google Sheet
named 'DrumAndBassHeadsUK Spreadsheets.' It is created using Python and is intended for sale to the
Discord user Nathan Essex.

All rights reserved. Unauthorized use, distribution, or modification of this code is prohibited. For more inquery or
support join this Discord server - https://discord.gg/jqfyu6UfPS or visit here - https://xdevelopments.in/

"""

import os
import discord
import gspread
import requests
from discord.ext.commands import CommandOnCooldown
from discord.ext import commands, tasks
from oauth2client.service_account import ServiceAccountCredentials
from pytz import timezone
from urllib.parse import urlparse, urlunparse
import re
from bs4 import BeautifulSoup
import time
import dotenv
from discord.ui import View, Button
from dotenv import load_dotenv
from discord import app_commands
from datetime import datetime, timedelta
import datetime as dt
from collections import Counter
import asyncio
import json
import traceback

# Google Sheets API
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("discordbot-uvrr-413076a6b997.json", scope)
client = gspread.authorize(creds)
sheet = client.open("DrumAndBassHeadsUK Spreadsheets").sheet1

load_dotenv()

link_emoji = "<:xdev_external_link:1293887507565379635>"

# # Track warnings for ctx commands
# user_warnings = {}

# Track warning and cooldown for on_message function

user_cooldowns = {}

COOLDOWN_DURATION = 2

# File to store assigned roles persistently
ROLE_TRACKING_FILE = "assigned_roles.json"

# log things
LOG_CHANNEL_ID = 1353659260625621024
LOG_FILE_PATH = 'nohup.out'

# Configuration for retries and notification channel
MAX_RETRIES = 5
BASE_BACKOFF = 2  # seconds
NOTIFICATION_CHANNEL_ID = 1200530700600889404

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.dm_messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(e)
    send_log.start()
"""Helper Functions"""


@tasks.loop(minutes=5)
async def send_log():
    try:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel is not None:
            with open(LOG_FILE_PATH, 'r') as log_file:
                log_content = log_file.read()
                if len(log_content) > 1900:
                    log_content = log_content[-1900:]
                await channel.send(f'Log Update:\n{log_content}')
        else:
            print(f'Channel with ID {LOG_CHANNEL_ID} not found.')
    except Exception as e:
        print(f'Error sending log: {e}')



# Function For Thumbnail Fetching
def fetch_thumbnail(link):
    try:
        # Handle YouTube links separately
        if 'youtube.com' in link or 'youtu.be' in link:
            # Extract video ID from the link
            video_id = None
            if 'youtu.be' in link:
                video_id = link.split('/')[-1].split('?')[0]
            elif 'youtube.com' in link:
                video_id = re.search(r'v=([^&]+)', link)
                if video_id:
                    video_id = video_id.group(1)

            if video_id:
                # Construct standard YouTube thumbnail URL
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                return thumbnail_url
            else:
                return None
        # Handle SoundCloud links
        if 'soundcloud.com' in link:
            response = requests.get(link)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tag = soup.find('meta', property='twitter:image')
            if meta_tag:
                return meta_tag.get('content')
            else:
                return None
        else:
            # For other links
            response = requests.get(link)
            response.raise_for_status()

            # Try finding og:image
            soup = BeautifulSoup(response.text, 'html.parser')
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image['content']:
                return og_image['content']

            # Fallback to regex search if no og:image tag found
            match = re.search(r'og:image" content="(.*?)"', response.text)
            if match:
                return match.group(1)
            else:
                return None

    except Exception as e:
        return None


def get_previous_friday():
    today = datetime.today().date()  # Get today's date
    if today.weekday() == 4:
        last_friday = today - timedelta(days=7)
    elif today.weekday() < 4:
        offset = (today.weekday() - 4) % 7
        last_friday = today - timedelta(days=offset)
    else:
        offset = (today.weekday() - 4) % 7
        last_friday = today - timedelta(days=offset + 7)
    return last_friday


def get_this_friday():
    today = datetime.today().date()  # Get today's date
    weekday = today.weekday()

    # Calculate the offset to the next Friday
    offset_to_next_friday = (4 - weekday + 7) % 7
    next_friday = today + timedelta(days=offset_to_next_friday)

    # If today is Saturday or Sunday, return the current week's Friday
    if weekday >= 5:
        current_week_friday = today - timedelta(days=(weekday - 4))
        if current_week_friday > today:
            current_week_friday -= timedelta(days=7)
        return current_week_friday
    else:
        return next_friday


# Function to clean and parse date strings 
def parse_date(date_str):
    try:
        # Extract the 'dd/mm/yy' part from the string
        date_part = date_str.split(" ")[1]  # Assumes format: 'DayName dd/mm/yy'
        return datetime.strptime(date_part, '%d/%m/%y')
    except (IndexError, ValueError):
        return None  # Return None if the format is invalid



# Function for sending embed messages (tree commands)
async def send_embed(interaction, rows, date):
    # Fetch the color from the first row's 'Colour' field
    color_value = rows[0].get('Colour', None)

    # Set the default color to blue if no valid color is found
    color = discord.Color.blue()
    if color_value:
        try:
            # Convert the color value (e.g., "#3618f6") into a valid Discord Color
            color = discord.Color(int(color_value.strip('#'), 16))
        except ValueError:
            print(f"Invalid color value: {color_value}. Defaulting to blue.")

    embed = discord.Embed(
        title=f"New Music {rows[0]['Date']}",
        color=color,
    )

    entry_lines = ""
    # Fetch the Thumbnail Image link from the first row (if available)
    thumbnail_image_url = rows[0].get('Thumbnail Image', None)

    for index, row in enumerate(rows):
        # Get the Discord ID and format it as a mention
        discord_id = row.get('Discord')
        user_mention = f"<@{discord_id}>"
        
        # Get the Song Name
        song_name = row.get('Song Name', 'Unknown Track')
        
        # Get the Listen Link
        listen_link = row.get('Listen Link', '')
        
        # Format the song name as a hyperlink with the listen link
        if listen_link:
            song_formatted = f"[{song_name}]({listen_link})"
        else:
            song_formatted = song_name

        # Get the Buy / Hypeddit link if available
        buy_link = row.get('Buy / Hypeddit', '')
        buy_formatted = f"[Buy]({buy_link})" if buy_link and buy_link.strip() != "" else ""

        # Build the entry line: user - Song Name - Buy (omit Buy if not present)
        if buy_formatted:
            line = f"{song_formatted} - {user_mention} - {buy_formatted}"
        else:
            line = f"{song_formatted} - {user_mention}"
        entry_lines += f"{index + 1}. {line}\n"

        # Thumbnail: for the first row, set an image from the Thumbnail Image field
        if index == 0:
            if thumbnail_image_url:
                embed.set_image(url=thumbnail_image_url)
            else:
                fetched_thumbnail_url = fetch_thumbnail(listen_link)
                embed.set_image(url=fetched_thumbnail_url)

    # Add a single embed field containing all the entries
    embed.add_field(name="Submissions", value=entry_lines, inline=False)

    # Use week image as thumbnail if available (overrides the default thumbnail set above)
    week_image_url = rows[0].get('Week Image', None)
    if week_image_url:
        embed.set_thumbnail(url=week_image_url)

    embed.set_footer(text=f"{rows[0]['Comment']}")

    await interaction.followup.send(embed=embed)


# Function for sending embed messages (ctx commands)
async def ctx_send_embed(ctx, rows, date):
    # Fetch the color from the first row's 'Colour' field
    color_value = rows[0].get('Colour', None)

    # Set the default color to blue if no valid color is found
    color = discord.Color.blue()
    if color_value:
        try:
            # Convert the color value (e.g., "#3618f6") into a valid Discord Color
            color = discord.Color(int(color_value.strip('#'), 16))
        except ValueError:
            print(f"Invalid color value: {color_value}. Defaulting to blue.")

    embed = discord.Embed(
        title=f"New Music {rows[0]['Date']}",
        color=color,
    )

    entry_lines = ""
    # Fetch the Thumbnail Image link from the first row (if available)
    thumbnail_image_url = rows[0].get('Thumbnail Image', None)

    for index, row in enumerate(rows):
        # Get the Discord ID and format it as a mention
        discord_id = row.get('Discord')
        user_mention = f"<@{discord_id}>"
        
        # Get the Song Name
        song_name = row.get('Song Name', 'Unknown Track')
        
        # Get the Listen Link
        listen_link = row.get('Listen Link', '')
        
        # Format the song name as a hyperlink with the listen link
        if listen_link:
            song_formatted = f"[{song_name}]({listen_link})"
        else:
            song_formatted = song_name

        # Get the Buy / Hypeddit link if available
        buy_link = row.get('Buy / Hypeddit', '')
        buy_formatted = f"[Buy]({buy_link})" if buy_link and buy_link.strip() != "" else ""

        # Build the entry line: user - Song Name - Buy (omit Buy if not present)
        if buy_formatted:
            line = f"{song_formatted} - {user_mention} - {buy_formatted}"
        else:
            line = f"{song_formatted} - {user_mention}"
        entry_lines += f"{index + 1}. {line}\n"

        # Thumbnail: for the first row, set an image from the Thumbnail Image field
        if index == 0:
            if thumbnail_image_url:
                embed.set_image(url=thumbnail_image_url)
            else:
                fetched_thumbnail_url = fetch_thumbnail(listen_link)
                embed.set_image(url=fetched_thumbnail_url)

    # Add a single embed field containing all the entries
    embed.add_field(name="Submissions", value=entry_lines, inline=False)

    # Use week image as thumbnail if available (overrides the default thumbnail set above)
    week_image_url = rows[0].get('Week Image', None)
    if week_image_url:
        embed.set_thumbnail(url=week_image_url)

    embed.set_footer(text=f"{rows[0]['Comment']}")

    # Changed from interaction.followup.send to ctx.send
    await ctx.send(embed=embed)


# FUnction to create commands embed (help command wala)
def create_commands_embed(author):
    embed = discord.Embed(
        title="Commands",
        color=discord.Color.blue()
    )

    # Existing fields
    embed.add_field(name="!week [space] `<week_number>` or /week `<week_number>`",
                    value="Tells you info for what week.",
                    inline=False)
    embed.add_field(name="!lastweek or /lastweek", value="Last weeks NMF.", inline=False)
    embed.add_field(name="!thisweek or /thisweek", value="Newest NMF.", inline=False)
    embed.add_field(name="!profile [space] `@user` or /profile `@user`",
                    value="Check your own stats or mention another user to see their stats. If no user is mentioned, "
                          "it will show your own stats.",
                    inline=False)
    embed.add_field(name="**__New Music Friday Seasons__**\n!season !lastseason !season1 !leaderboard1 or /season1",
                    value="Check to see whose tracks got mentioned most in NMF Season 1.",
                    inline=False)

    embed.add_field(name="!thisseason !currentseason !season2 !leaderboard2 or /season2",
                    value="Check to see whose tracks got mentioned most in NMF Season 2.",
                    inline=False)

    # Add field conditionally based on permissions
    if author.guild_permissions.manage_roles or author.guild_permissions.kick_members:
        embed.add_field(
            name="!autoassign `<season_number>`",
            value="Override manually & generates mentions role.",
            inline=False
        )

    return embed


# Function to check if the user is on cooldown for the commands embed
def is_user_on_cooldown(user_id):
    if user_id not in user_cooldowns:
        return False
    return time.time() - user_cooldowns[user_id] < COOLDOWN_DURATION


# Function to set the user cooldown
def set_user_cooldown(user_id):
    user_cooldowns[user_id] = time.time()


async def handle_command_help(message):
    author_id = message.author.id

    # Check if the user is on cooldown and if so, do nothing (no message)
    if is_user_on_cooldown(author_id):
        return

    # Send embed and set cooldown
    embed = create_commands_embed(message.author)
    await message.channel.send(embed=embed)
    set_user_cooldown(author_id)


""" Tree Commands """


# Week command
@bot.tree.command(name="week", description="Fetch the winner(s) of a specified week")
@app_commands.describe(
    week_number="The week number to fetch the winner(s) for.",
)
async def send_weekly_winner_embed(interaction: discord.Interaction, week_number: int):
    await interaction.response.defer()

    try:
        # Expected headers
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Comment', 'Buy / Hypeddit',
                            'Week Image', 'Colour', 'Thumbnail Image']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # print(f"All Data: {data}")

        rows = [row for row in data if int(row['Week'].replace('Week ', '').strip()) == week_number]

        # print(f"Filtered Rows for Week {week_number}: {rows}")

        if not rows:
            await interaction.followup.send(f"Week {week_number} not found in the spreadsheet.")
            return

        #  date from the first row
        week_date = rows[0]['Date']
        await send_embed(interaction, rows, week_date)

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")
        print(f"Error: {e}")


# Previous week command
@bot.tree.command(name="lastweek", description="Fetch the winner(s) of last Friday")
async def send_last_week_embed(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        # Get the previous Friday's date
        previous_friday = get_previous_friday().strftime('%A %d/%m/%y')

        # Expected headers in the Google Sheet
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Comment', 'Buy / Hypeddit',
                            'Week Image', 'Colour', 'Thumbnail Image']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # Fetch rows for the previous Friday
        rows = [row for row in data if row['Date'] == previous_friday]

        if not rows:
            await interaction.followup.send(f"No data found for {previous_friday}.")
            return

        # Same logic as the week command for generating the embed
        await send_embed(interaction, rows, previous_friday)

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")
        print(f"Error: {e}")


# This week command
@bot.tree.command(name="thisweek", description="Fetch the winner(s) of this week's Friday")
async def send_this_week_embed(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        # this week's Friday's date
        this_friday = get_this_friday().strftime('%A %d/%m/%y')

        # Expected headers
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Comment', 'Buy / Hypeddit',
                            'Week Image', 'Colour', 'Thumbnail Image']
        data = sheet.get_all_records(expected_headers=expected_headers)

        rows = [row for row in data if row['Date'] == this_friday]

        if not rows:
            await interaction.followup.send("Coming soon, please wait. Data for this Friday is not yet uploaded.")
            return

        await send_embed(interaction, rows, this_friday)

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")
        print(f"Error: {e}")




@bot.tree.command(name="profile", description="Fetch your stats or another users.")
@app_commands.describe(
    user="Select the user.",
)
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()

    if user is None:
        user = interaction.user

    discord_id = str(user.id)
    excluded_user_id = '762317361822564412'

    try:
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Roles for Profile']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # -------------------------------
        # Calculate Overall Rank (All-time mentions)
        # -------------------------------
        overall_mention_counts = {}
        for row in data:
            uid = str(row.get('Discord'))
            if uid and uid != excluded_user_id:
                overall_mention_counts[uid] = overall_mention_counts.get(uid, 0) + 1

        overall_rank_field = None
        if discord_id in overall_mention_counts:
            sorted_overall = sorted(overall_mention_counts.items(), key=lambda x: x[1], reverse=True)
            for idx, (uid, _) in enumerate(sorted_overall):
                if uid == discord_id:
                    overall_rank_field = idx + 1
                    break
        elif discord_id != excluded_user_id:
            overall_rank_field = len(overall_mention_counts) + 1

        # -------------------------------
        # Calculate Leaderboard Rank (Season period)
        # -------------------------------
        period_start = datetime(2024, 12, 3)
        period_end = datetime(2025, 12, 2)

        ranking_counts = {}
        for row in data:
            date_val = parse_date(row['Date'])
            if date_val and period_start <= date_val <= period_end:
                uid = str(row.get('Discord'))
                if uid and uid != excluded_user_id:
                    ranking_counts[uid] = ranking_counts.get(uid, 0) + 1

        leaderboard_rank_field = None
        if discord_id in ranking_counts:
            sorted_season = sorted(
                {k: v for k, v in ranking_counts.items() if k != excluded_user_id}.items(),
                key=lambda x: x[1], reverse=True
            )
            for idx, (uid, _) in enumerate(sorted_season):
                if uid == discord_id:
                    leaderboard_rank_field = idx + 1
                    break
        elif discord_id != excluded_user_id:
            leaderboard_rank_field = len(ranking_counts) + 1
        if discord_id == excluded_user_id:
            overall_rank_field = '-'
            leaderboard_rank_field = '-'

        # -------------------------------
        # Filter user data
        # -------------------------------
        user_data = [r for r in data if str(r.get('Discord')) == discord_id]
        if not user_data:
            await interaction.followup.send(f"No data found for {user.mention}.")
            return

        user_data.sort(key=lambda r: parse_date(r['Date']) or datetime.min, reverse=True)

        # Extract roles
        role_ids_from_sheet = set()
        for row in data:
            roles = row.get('Roles for Profile', "")
            if roles:
                try:
                    if isinstance(roles, int):
                        role_ids_from_sheet.add(roles)
                    elif isinstance(roles, str):
                        valid = [int(x.strip()) for x in roles.split(',') if x.strip().isdigit()]
                        role_ids_from_sheet.update(valid)
                except ValueError:
                    print(f"Warning: Could not parse role ID from '{roles}' in sheet.")

        user_role_ids = {role.id for role in user.roles}
        matched = user_role_ids.intersection(role_ids_from_sheet)
        matched_mentions = [f"<@&{rid}>" for rid in matched]

        # Build pages
        pages = []
        per_page = 5
        batch = []

        def make_embed(entries):
            emb = discord.Embed(
                title=f"{user.display_name}'s NMF Profile",
                color=discord.Color.from_str("#3618f6"),
                timestamp=datetime.now(dt.timezone.utc)
            )
            emb.set_thumbnail(url=user.avatar.url)
            emb.add_field(name="Selection(s)", value="\n".join(entries), inline=False)
            if matched_mentions:
                emb.add_field(name="Awarded", value=" ".join(matched_mentions), inline=False)
            emb.add_field(name="Total Mentions", value=f"**{len(user_data)}**", inline=True)
            if overall_rank_field is not None:
                emb.add_field(name="Overall Rank", value=f"**{overall_rank_field}**", inline=True)
            if leaderboard_rank_field is not None:
                emb.add_field(name="Season Rank", value=f"**{leaderboard_rank_field}**", inline=True)
            return emb

        for row in user_data:
            week = row.get('Week', 'Unknown Week')
            song = row.get('Song Name', 'Unknown Song')
            link = row.get('Listen Link', '')
            batch.append(f"{week} - [{song}]({link})")
            if len(batch) >= per_page:
                pages.append(make_embed(batch))
                batch = []
        if batch:
            pages.append(make_embed(batch))

        # Pagination
        class PaginationView(View):
            def __init__(self, pages, user):
                super().__init__(timeout=None)
                self.pages = pages
                self.current = 0
                self.user = user
                if len(pages) <= 1:
                    self.children[1].disabled = True

            async def interaction_check(self, interaction):
                return interaction.user == self.user

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
            async def prev(self, interaction, button: Button):
                self.current = max(self.current - 1, 0)
                button.disabled = self.current == 0
                self.children[1].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current], view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
            async def nxt(self, interaction, button: Button):
                self.current = min(self.current + 1, len(self.pages) - 1)
                button.disabled = self.current == len(self.pages) - 1
                self.children[0].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current], view=self)

        if len(pages) > 1:
            view = PaginationView(pages, interaction.user)
            await interaction.followup.send(embed=pages[0], view=view)
        else:
            await interaction.followup.send(embed=pages[0])

    except gspread.exceptions.APIError as e:
        await interaction.followup.send(f"Error accessing Google Sheet. Please check credentials and sheet permissions. Details: {e}")
        print(f"GSpread API Error: {e}")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}")
        traceback.print_exc()
# Season1 Leaderboard Command
@bot.tree.command(name="season1", description="Display the Season 1 leaderboard.")
async def season1(interaction: discord.Interaction):
    await interaction.response.defer()
    excluded_user_id = '762317361822564412'

    try:
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link',
                            'Season starts 4th December', 'NMF Leaderboard Thumbnail', 'Top right image',
                            'Leaderboard Colour']
        data = sheet.get_all_records(expected_headers=expected_headers)

        season_metadata_row = next((row for row in data if row.get('Season starts 4th December') == 'Season1'), None)
        if not season_metadata_row:
            await interaction.followup.send("Season 1 metadata not found in the spreadsheet.")
            return

        nmf_leaderboard_thumbnail = season_metadata_row.get('NMF Leaderboard Thumbnail', '')
        top_right_image = season_metadata_row.get('Top right image', '')
        thumbnail_colour = season_metadata_row.get('Leaderboard Colour', '#000000')

        # Fetch Season 1 leaderboard data (Weeks 1-49)
        season1_data = [row for row in data if
                        'Week' in row and row['Week'].startswith("Week") and int(row['Week'].split()[1]) <= 49]

        # Count mentions for each Discord ID
        mention_counts = {}
        user_names = {}
        for row in season1_data:
            discord_id = str(row['Discord'])
            name = row['Name']
            mention_counts[discord_id] = mention_counts.get(discord_id, 0) + 1
            user_names[discord_id] = name

            # Sort leaderboard by mentions
        sorted_leaderboard = sorted(mention_counts.items(), key=lambda x: x[1], reverse=True)
        # Remove excluded user from the leaderboard
        filtered_leaderboard = [item for item in sorted_leaderboard if item[0] != excluded_user_id]
        total_entries = len(filtered_leaderboard)

        # Paginate leaderboard (5 users per page)
        pages = []
        users_per_page = 10
        for i in range(0, len(filtered_leaderboard), users_per_page):
            page_data = filtered_leaderboard[i:i + users_per_page]
            leaderboard_lines = []
            for index, (user_id, mention_count) in enumerate(page_data, start=i + 1):
                # Convert user_id to string and check validity
                user_id = str(user_id)
                if user_id.isdigit():
                    mention = f"<@{user_id}>"
                else:
                    mention = user_names.get(user_id, "Unknown User")

                leaderboard_lines.append(f"**{index}.** {mention} — **{mention_count} mentions**")
            embed_description = (
                f"👥 Drum&BassHeadsUK\n"
                f"👑Leaderboard👑\n"
                f"👉 Season: 1\n"
                f"👫 Entries: {total_entries}\n\n"
                f"" + "\n".join(leaderboard_lines)
            )

            # Create embed
            embed = discord.Embed(
                description=embed_description,
                color=discord.Color.from_str(thumbnail_colour),
            )
            current_page_num = i // users_per_page + 1
            embed.set_footer(text=f"Page {current_page_num}")
            embed.set_thumbnail(url=top_right_image)
            embed.set_image(url=nmf_leaderboard_thumbnail)
            pages.append(embed)

        # Pagination logic
        class PaginationView(View):
            def __init__(self, pages, original_user):
                super().__init__(timeout=None)
                self.pages = pages
                self.current_page = 0
                self.original_user = original_user
                self.user_warnings = set()

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user != self.original_user:
                    if interaction.user.id not in self.user_warnings:
                        await interaction.response.send_message(
                            f"This was opened by {self.original_user.mention}, you can't do that!",
                            ephemeral=True
                        )
                        self.user_warnings.add(interaction.user.id)
                    return False
                return True

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
            async def previous_button(self, interaction: discord.Interaction, button: Button):
                self.current_page -= 1
                if self.current_page <= 0:
                    self.current_page = 0
                    button.disabled = True
                self.children[1].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
            async def next_button(self, interaction: discord.Interaction, button: Button):
                self.current_page += 1
                if self.current_page >= len(self.pages) - 1:
                    self.current_page = len(self.pages) - 1
                    button.disabled = True
                self.children[0].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

        # Send the leaderboard
        if len(pages) > 1:
            view = PaginationView(pages, interaction.user)
            await interaction.followup.send(embed=pages[0], view=view)
        else:
            await interaction.followup.send(embed=pages[0])

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")
        print(f"Error: {e}")


# Season2 Leaderboard Command
@bot.tree.command(name="season2", description="Display the Season 2 leaderboard.")
async def season2(interaction: discord.Interaction):
    await interaction.response.defer()
    excluded_user_id = '762317361822564412'

    try:
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link',
                            'Season starts 4th December', 'NMF Leaderboard Thumbnail', 'Top right image',
                            'Leaderboard Colour']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # Filter metadata for Season 2
        season_metadata_row = next((row for row in data if row.get('Season starts 4th December') == 'Season2'), None)
        if not season_metadata_row:
            await interaction.followup.send("Season 2 metadata not found in the spreadsheet.")
            return

        # Extract Season 2 metadata
        nmf_leaderboard_thumbnail = season_metadata_row.get('NMF Leaderboard Thumbnail', '')
        top_right_image = season_metadata_row.get('Top right image', '')
        thumbnail_colour = season_metadata_row.get('Leaderboard Colour', '#000000')

        # Season 2 date range
        season2_start = datetime(2024, 12, 3)
        season2_end = datetime(2025, 12, 2)

        # Filter Season 2 data based on the date range
        season2_data = [
            row for row in data
            if 'Date' in row and parse_date(row['Date']) and season2_start <= parse_date(row['Date']) <= season2_end
        ]

        mention_counts = {}
        user_names = {}
        for row in season2_data:
            discord_id = str(row['Discord'])
            name = row['Name']
            mention_counts[discord_id] = mention_counts.get(discord_id, 0) + 1
            user_names[discord_id] = name

        sorted_leaderboard = sorted(mention_counts.items(), key=lambda x: x[1], reverse=True)
        filtered_leaderboard = [item for item in sorted_leaderboard if item[0] != excluded_user_id]
        total_entries = len(filtered_leaderboard)

        # Paginate leaderboard (5 users per page)
        pages = []
        users_per_page = 10
        for i in range(0, len(filtered_leaderboard), users_per_page):
            page_data = filtered_leaderboard[i:i + users_per_page]
            leaderboard_lines = []
            for index, (user_id, mention_count) in enumerate(page_data, start=i + 1):
                user_id = str(user_id)
                if user_id.isdigit():
                    mention = f"<@{user_id}>"
                else:
                    mention = user_names.get(user_id, "Unknown User")

                leaderboard_lines.append(f"**{index}.** {mention} — **{mention_count} mentions**")
            embed_description = (
                f"👥 Drum&BassHeadsUK\n"
                f"👑Leaderboard👑\n"
                f"👉 Season: 2\n"
                f"👫 Entries: {total_entries}\n\n"
                f"" + "\n".join(leaderboard_lines)
            )

            # Create embed
            embed = discord.Embed(
                description=embed_description,
                color=discord.Color.from_str(thumbnail_colour),
            )
            current_page_num = i // users_per_page + 1
            embed.set_footer(text=f"Page {current_page_num}")
            embed.set_thumbnail(url=top_right_image)
            embed.set_image(url=nmf_leaderboard_thumbnail)
            pages.append(embed)

        # Pagination logic
        class PaginationView(View):
            def __init__(self, pages, original_user):
                super().__init__(timeout=None)
                self.pages = pages
                self.current_page = 0
                self.original_user = original_user
                self.user_warnings = set()

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user != self.original_user:
                    if interaction.user.id not in self.user_warnings:
                        await interaction.response.send_message(
                            f"This was opened by {self.original_user.mention}, you can't do that!",
                            ephemeral=True
                        )
                        self.user_warnings.add(interaction.user.id)
                    return False
                return True

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
            async def previous_button(self, interaction: discord.Interaction, button: Button):
                self.current_page -= 1
                if self.current_page <= 0:
                    self.current_page = 0
                    button.disabled = True
                self.children[1].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
            async def next_button(self, interaction: discord.Interaction, button: Button):
                self.current_page += 1
                if self.current_page >= len(self.pages) - 1:
                    self.current_page = len(self.pages) - 1
                    button.disabled = True
                self.children[0].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

        # Send the leaderboard
        if len(pages) > 1:
            view = PaginationView(pages, interaction.user)
            await interaction.followup.send(embed=pages[0], view=view)
        else:
            await interaction.followup.send(embed=pages[0])

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")
        print(f"Error: {e}")


""" CTX command part """


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CommandOnCooldown):
        pass

    else:
        raise error


# Week Command
@bot.command(name="week")
@commands.cooldown(1, 2, commands.BucketType.user)
async def week(ctx, week_number: int):
    await ctx.defer()

    try:
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Comment', 'Buy / Hypeddit',
                            'Week Image', 'Colour', 'Thumbnail Image']
        data = sheet.get_all_records(expected_headers=expected_headers)

        rows = [row for row in data if int(row['Week'].replace('Week ', '').strip()) == week_number]

        if not rows:
            await ctx.send(f"Week {week_number} not found in the spreadsheet.")
            return

        week_date = rows[0]['Date']

        await ctx_send_embed(ctx, rows, week_date)

    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")


# Lastweek Command
@bot.command(name="lastweek")
@commands.cooldown(1, 2, commands.BucketType.user)
async def lastweek(ctx):
    await ctx.defer()

    try:
        previous_friday = get_previous_friday().strftime('%A %d/%m/%y')

        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Comment', 'Buy / Hypeddit',
                            'Week Image', 'Colour', 'Thumbnail Image']
        data = sheet.get_all_records(expected_headers=expected_headers)

        rows = [row for row in data if row['Date'] == previous_friday]

        if not rows:
            await ctx.send(f"No data found for {previous_friday}.")
            return

        await ctx_send_embed(ctx, rows, previous_friday)

    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")


# Thisweek Command
@bot.command(name="thisweek")
@commands.cooldown(1, 2, commands.BucketType.user)
async def thisweek(ctx):
    await ctx.defer()

    try:
        this_friday = get_this_friday().strftime('%A %d/%m/%y')

        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Comment', 'Buy / Hypeddit',
                            'Week Image', 'Colour', 'Thumbnail Image']
        data = sheet.get_all_records(expected_headers=expected_headers)

        rows = [row for row in data if row['Date'] == this_friday]

        if not rows:
            await ctx.send("Coming soon, please wait. Data for this Friday is not yet uploaded.")
            return

        await ctx_send_embed(ctx, rows, this_friday)

    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")

@bot.command(name="profile", description="Fetch your stats or another users.")
async def profile(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    
    discord_id = str(user.id)
    excluded_user_id = '762317361822564412'

    try:
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link', 'Roles for Profile']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # Overall Rank (All-time)
        overall_mention_counts = {}
        for row in data:
            uid = str(row.get('Discord'))
            if uid and uid != excluded_user_id:
                overall_mention_counts[uid] = overall_mention_counts.get(uid, 0) + 1
        overall_rank_field = None
        if discord_id in overall_mention_counts:
            sorted_overall = sorted(
                {k: v for k, v in overall_mention_counts.items() if k != excluded_user_id}.items(),
                key=lambda x: x[1], reverse=True
            )
            for idx, (uid, _) in enumerate(sorted_overall):
                if uid == discord_id:
                    overall_rank_field = idx + 1
                    break
        elif discord_id != excluded_user_id:
             overall_rank_field = len(overall_mention_counts) + 1

        # Leaderboard Rank (Season)
        period_start = datetime(2024, 12, 3)
        period_end = datetime(2025, 12, 2)
        ranking_counts = {}
        for row in data:
            date_val = parse_date(row['Date'])
            if date_val and period_start <= date_val <= period_end:
                uid = str(row.get('Discord'))
                if uid and uid != excluded_user_id:
                    ranking_counts[uid] = ranking_counts.get(uid, 0) + 1
        leaderboard_rank_field = None
        if discord_id in ranking_counts:
            sorted_season = sorted(ranking_counts.items(), key=lambda x: x[1], reverse=True)
            for idx, (uid, _) in enumerate(sorted_season):
                if uid == discord_id:
                    leaderboard_rank_field = idx + 1
                    break
        elif discord_id != excluded_user_id:
             leaderboard_rank_field = len(ranking_counts) + 1
             
        if discord_id == excluded_user_id:
            overall_rank_field = '-'
            leaderboard_rank_field = '-'

        # Filter user data
        user_data = [r for r in data if str(r.get('Discord')) == discord_id]
        if not user_data:
            await ctx.send(f"No data found for {user.mention}.")
            return
        user_data.sort(key=lambda r: parse_date(r['Date']) or datetime.min, reverse=True)

        # Roles
        role_ids_from_sheet = set()
        for row in data:
            roles = row.get('Roles for Profile', "")
            if roles:
                try:
                    if isinstance(roles, int):
                        role_ids_from_sheet.add(roles)
                    elif isinstance(roles, str):
                        valid = [int(x.strip()) for x in roles.split(',') if x.strip().isdigit()]
                        role_ids_from_sheet.update(valid)
                except ValueError:
                    print(f"Warning: Could not parse role ID from '{roles}' in sheet.")
        user_role_ids = {role.id for role in user.roles}
        matched = user_role_ids.intersection(role_ids_from_sheet)
        matched_mentions = [f"<@&{rid}>" for rid in matched]

        # Build pages & pagination (same as above)
        pages = []
        per_page = 5
        batch = []
        def make_embed(entries):
            emb = discord.Embed(
                title=f"{user.display_name}'s NMF Profile",
                color=discord.Color.from_str("#3618f6"),
                timestamp=datetime.now(dt.timezone.utc)
            )
            emb.set_thumbnail(url=user.avatar.url)
            emb.add_field(name="Selection(s)", value="\n".join(entries), inline=False)
            if matched_mentions:
                emb.add_field(name="Awarded", value=" ".join(matched_mentions), inline=False)
            emb.add_field(name="Total Mentions", value=f"**{len(user_data)}**", inline=True)
            if overall_rank_field is not None:
                emb.add_field(name="Overall Rank", value=f"**{overall_rank_field}**", inline=True)
            if leaderboard_rank_field is not None:
                emb.add_field(name="Season Rank", value=f"**{leaderboard_rank_field}**", inline=True)
            return emb
        for row in user_data:
            week = row.get('Week', 'Unknown Week')
            song = row.get('Song Name', 'Unknown Song')
            link = row.get('Listen Link', '')
            batch.append(f"{week} - [{song}]({link})")
            if len(batch) >= per_page:
                pages.append(make_embed(batch)); batch = []
        if batch: pages.append(make_embed(batch))

        if not pages:
            await ctx.send("Could not generate profile embed.")
            return
        message = await ctx.send(embed=pages[0])

        if len(pages) > 1:
            class PaginationView(View):
                def __init__(self, pages, user, message):
                    super().__init__(timeout=180)
                    self.pages = pages; self.current = 0; self.user = user; self.message = message
                    if len(pages) <= 1: self.children[1].disabled = True

                async def interaction_check(self, interaction):
                    if interaction.user != self.user:
                        await interaction.response.send_message("You cannot control this pagination.", ephemeral=True)
                        return False
                    return True

                @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
                async def prev(self, interaction, button: Button):
                    self.current = max(self.current-1, 0)
                    button.disabled = self.current == 0
                    self.children[1].disabled = False
                    await interaction.response.edit_message(embed=self.pages[self.current], view=self)

                @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
                async def nxt(self, interaction, button: Button):
                    self.current = min(self.current+1, len(self.pages)-1)
                    button.disabled = self.current == len(self.pages)-1
                    self.children[0].disabled = False
                    await interaction.response.edit_message(embed=self.pages[self.current], view=self)

                async def on_timeout(self):
                    for item in self.children: item.disabled = True
                    try:
                        orig = await ctx.channel.fetch_message(self.message.id)
                        await orig.edit(view=self)
                    except Exception:
                        pass

            view = PaginationView(pages, ctx.author, message)
            await message.edit(embed=pages[0], view=view)

    except gspread.exceptions.APIError as e:
        await ctx.send(f"Error accessing Google Sheet. Please check credentials and sheet permissions. Details: {e}")
        print(f"GSpread API Error: {e}")
    except Exception as e:
        await ctx.send(f"An unexpected error occurred: {e}")
        traceback.print_exc()

# Season1 Leaderboard Command
@bot.command(name="season1", aliases=['lastseason', 'leaderboard1'],
             description="Display the Season 1 leaderboard.")
async def season1(ctx):
    loading_message = await ctx.send("Loading leaderboard...")
    excluded_user_id = '762317361822564412'

    try:
        # Fetch all spreadsheet data
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link',
                            'Season starts 4th December', 'NMF Leaderboard Thumbnail', 'Top right image',
                            'Leaderboard Colour']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # Filter metadata for Season 1
        season_metadata_row = next((row for row in data if row.get('Season starts 4th December') == 'Season1'), None)
        if not season_metadata_row:
            await loading_message.edit(content="Season 1 metadata not found in the spreadsheet.")
            return

        # Extract Season 1 metadata
        nmf_leaderboard_thumbnail = season_metadata_row.get('NMF Leaderboard Thumbnail', '')
        top_right_image = season_metadata_row.get('Top right image', '')
        thumbnail_colour = season_metadata_row.get('Leaderboard Colour', '#000000')

        # Fetch Season 1 leaderboard data (Weeks 1-49)
        season1_data = [row for row in data if
                        'Week' in row and row['Week'].startswith("Week") and int(row['Week'].split()[1]) <= 49]

        mention_counts = {}
        user_names = {}
        for row in season1_data:
            discord_id = str(row['Discord'])
            name = row['Name']
            mention_counts[discord_id] = mention_counts.get(discord_id, 0) + 1
            user_names[discord_id] = name

            # Sort leaderboard by mentions
        sorted_leaderboard = sorted(mention_counts.items(), key=lambda x: x[1], reverse=True)

        filtered_leaderboard = [item for item in sorted_leaderboard if item[0] != excluded_user_id]
        total_entries = len(filtered_leaderboard)

        # Paginate leaderboard (5 users per page)
        pages = []
        users_per_page = 10
        for i in range(0, len(filtered_leaderboard), users_per_page):
            page_data = filtered_leaderboard[i:i + users_per_page]
            leaderboard_lines = []
            for index, (user_id, mention_count) in enumerate(page_data, start=i + 1):
                # Convert user_id to string and check validity
                user_id = str(user_id)
                if user_id.isdigit():
                    mention = f"<@{user_id}>"
                else:
                    mention = user_names.get(user_id, "Unknown User")

                leaderboard_lines.append(f"**{index}.** {mention} — **{mention_count} mentions**")
            embed_description = (
                f"👥 Drum&BassHeadsUK\n"
                f"👑Leaderboard👑\n"
                f"👉 Season: 1\n"
                f"👫 Entries: {total_entries}\n\n"
                f"" + "\n".join(leaderboard_lines)
            )

            # Create embed
            embed = discord.Embed(
                description=embed_description,
                color=discord.Color.from_str(thumbnail_colour),
            )
            current_page_num = i // users_per_page + 1
            embed.set_footer(text=f"Page {current_page_num}")
            embed.set_thumbnail(url=top_right_image)
            embed.set_image(url=nmf_leaderboard_thumbnail)
            pages.append(embed)

        # Pagination logic for ctx commands
        class PaginationView(discord.ui.View):
            def __init__(self, pages, original_user):
                super().__init__(timeout=None)
                self.pages = pages
                self.current_page = 0
                self.original_user = original_user
                self.user_warnings = set()

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user != self.original_user:
                    if interaction.user.id not in self.user_warnings:
                        await interaction.response.send_message(
                            f"This was opened by {self.original_user.mention}, you can't do that!",
                            ephemeral=True
                        )
                        self.user_warnings.add(interaction.user.id)
                    return False
                return True

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
            async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page -= 1
                if self.current_page <= 0:
                    self.current_page = 0
                    button.disabled = True
                self.children[1].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
            async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page += 1
                if self.current_page >= len(self.pages) - 1:
                    self.current_page = len(self.pages) - 1
                    button.disabled = True
                self.children[0].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

        # Delete the loading message
        await loading_message.delete()

        # Send the leaderboard
        if len(pages) > 1:
            view = PaginationView(pages, ctx.author)
            await ctx.send(embed=pages[0], view=view)
        else:
            await ctx.send(embed=pages[0])

    except Exception as e:
        if loading_message:
            await loading_message.edit(content=f"An error occurred: {e}")
        else:
            await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")


# Season2 Leaderboard Command
@bot.command(name="season2", aliases=['thisseason', 'currentseason', 'leaderboard2'],
             description="Display the Season 2 leaderboard.")
async def season2(ctx):
    loading_message = await ctx.send("Loading leaderboard...")
    excluded_user_id = '762317361822564412'

    try:
        # Fetch all spreadsheet data
        expected_headers = ['Week', 'Date', 'Name', 'Discord', 'Song Name', 'Listen Link',
                            'Season starts 4th December', 'NMF Leaderboard Thumbnail', 'Top right image',
                            'Leaderboard Colour']
        data = sheet.get_all_records(expected_headers=expected_headers)

        # Filter metadata for Season 2
        season_metadata_row = next((row for row in data if row.get('Season starts 4th December') == 'Season2'), None)
        if not season_metadata_row:
            await loading_message.edit(content="Season 2 metadata not found in the spreadsheet.")
            return

        # Extract Season 2 metadata
        nmf_leaderboard_thumbnail = season_metadata_row.get('NMF Leaderboard Thumbnail', '')
        top_right_image = season_metadata_row.get('Top right image', '')
        thumbnail_colour = season_metadata_row.get('Leaderboard Colour', '#000000')

        # Define season 2 date range
        season2_start = datetime(2024, 12, 3)
        season2_end = datetime(2025, 12, 2)

        # Filter Season 2 data based on the date range
        season2_data = [
            row for row in data
            if 'Date' in row and parse_date(row['Date']) and season2_start <= parse_date(row['Date']) <= season2_end
        ]

        mention_counts = {}
        user_names = {}
        for row in season2_data:
            discord_id = str(row['Discord'])
            name = row['Name']
            mention_counts[discord_id] = mention_counts.get(discord_id, 0) + 1
            user_names[discord_id] = name

            # Sort leaderboard by mentions
        sorted_leaderboard = sorted(mention_counts.items(), key=lambda x: x[1], reverse=True)
        filtered_leaderboard = [item for item in sorted_leaderboard if item[0] != excluded_user_id]
        total_entries = len(filtered_leaderboard)

        # Paginate leaderboard (5 users per page)
        pages = []
        users_per_page = 10
        for i in range(0, len(filtered_leaderboard), users_per_page):
            page_data = filtered_leaderboard[i:i + users_per_page]
            leaderboard_lines = []
            for index, (user_id, mention_count) in enumerate(page_data, start=i + 1):
                # Convert user_id to string and check validity
                user_id = str(user_id)
                if user_id.isdigit():
                    mention = f"<@{user_id}>"
                else:
                    mention = user_names.get(user_id, "Unknown User")

                leaderboard_lines.append(f"**{index}.** {mention} — **{mention_count} mentions**")
            embed_description = (
                f"👥 Drum&BassHeadsUK\n"
                f"👑Leaderboard👑\n"
                f"👉 Season: 2\n"
                f"👫 Entries: {total_entries}\n\n"
                f"" + "\n".join(leaderboard_lines)
            )

            # Create embed
            embed = discord.Embed(
                description=embed_description,
                color=discord.Color.from_str(thumbnail_colour),
            )
            current_page_num = i // users_per_page + 1
            embed.set_footer(text=f"Page {current_page_num}")
            embed.set_thumbnail(url=top_right_image)
            embed.set_image(url=nmf_leaderboard_thumbnail)
            pages.append(embed)

        # Pagination logic for ctx commands
        class PaginationView(discord.ui.View):
            def __init__(self, pages, original_user):
                super().__init__(timeout=None)
                self.pages = pages
                self.current_page = 0
                self.original_user = original_user
                self.user_warnings = set()

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user != self.original_user:
                    if interaction.user.id not in self.user_warnings:
                        await interaction.response.send_message(
                            f"This was opened by {self.original_user.mention}, you can't do that!",
                            ephemeral=True
                        )
                        self.user_warnings.add(interaction.user.id)
                    return False
                return True

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
            async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page -= 1
                if self.current_page <= 0:
                    self.current_page = 0
                    button.disabled = True
                self.children[1].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
            async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page += 1
                if self.current_page >= len(self.pages) - 1:
                    self.current_page = len(self.pages) - 1
                    button.disabled = True
                self.children[0].disabled = False
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

        # Delete the loading message
        await loading_message.delete()

        # Send the leaderboard
        if len(pages) > 1:
            view = PaginationView(pages, ctx.author)
            await ctx.send(embed=pages[0], view=view)
        else:
            await ctx.send(embed=pages[0])

    except Exception as e:
        if loading_message:
            await loading_message.edit(content=f"An error occurred: {e}")
        else:
            await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")




@bot.command(name="autoassign")
@commands.has_permissions(manage_roles=True, kick_members=True)
async def autorole(ctx, season: int):
    processing_message = await ctx.send("Processing...")

    try:
        # Fetch all records
        data = sheet.get_all_records(expected_headers=['Week', 'Date', 'Discord', 'Autorole Seasons', 'Role Id'])
        # Build the dictionary of season -> role_id
        role_data = {}
        for row in data:
            if 'Autorole Seasons' in row and row['Autorole Seasons'] and 'Role Id' in row:
                try:
                    season_number = int(row['Autorole Seasons'])
                    role_id_value = int(row['Role Id'])
                    role_data[season_number] = role_id_value
                except ValueError:
                    print(f"Skipping row due to invalid season/role ID: {row}")



        # Check if the season is in role_data
        if season not in role_data:
            msg = f"No role ID found for season {season}. Please check the sheet."
            print(f"DEBUG: {msg}")
            await processing_message.edit(content=msg)
            return

        # Fetch the role from the guild
        role_id = role_data[season]
        role = ctx.guild.get_role(role_id)

        if not role:
            msg = f"Role with ID `{role_id}` not found in this server."
            await processing_message.edit(content=msg)
            return

        # -------------------------
        #         SEASON 2
        # -------------------------
        if season == 2:
            # Define date range
            try:
                start_date = datetime.strptime("03/12/24", "%d/%m/%y")
                end_date = datetime.strptime("02/12/25", "%d/%m/%y")
            except Exception as e:
                msg = f"Error parsing date boundaries: {e}"
                print(f"DEBUG: {msg}")
                await processing_message.edit(content=msg)
                return

            # Filter rows based on Date column
            season_data = []
            for row in data:
                # Make sure 'Date' column exists and is non-empty
                if 'Date' in row and row['Date']:
                    # We expect something like "Friday 08/03/24"
                    parts = row['Date'].split()
                    if len(parts) > 1:
                        date_str = parts[1]  # "08/03/24"
                        try:
                            row_date = datetime.strptime(date_str, "%d/%m/%y")
                            # Check if within range
                            if start_date <= row_date <= end_date:
                                season_data.append(row)
                            else:
                                print(f"DEBUG: Row date out of range => {row}")
                        except ValueError:
                            print(f"DEBUG: Could not parse date => {row}")
                    else:
                        print(f"DEBUG: Date format not recognized => {row['Date']}")
                else:
                    print(f"DEBUG: No valid 'Date' found => {row}")


            for sd in season_data:
                print(sd)
            # Now gather Discord IDs from season_data
            discord_ids = []
            for row in season_data:
                if row.get('Discord'):
                    discord_ids.append(row['Discord'])



            # Convert to int where possible
            valid_ids = []
            for discord_id in discord_ids:
                try:
                    valid_ids.append(int(discord_id))
                except ValueError:
                    print(f"DEBUG: Skipping invalid Discord ID => {discord_id}")

 
            # Count occurrences
            user_counts = Counter(valid_ids)


            # Eligible if user appears >= 3 times
            eligible_users = {user_id: count for user_id, count in user_counts.items() if count >= 3}

            # Tracking
            not_in_server = []
            successfully_assigned = []

            # Assign roles
            for user_id, count in eligible_users.items():
                member = ctx.guild.get_member(user_id)
                if not member:
                    not_in_server.append(user_id)
                    continue

                # Skip if member already has the role
                if role in member.roles:
                    print(f"DEBUG: Member {user_id} already has the role.")
                    continue

                # Attempt to assign role
                try:
                    await member.add_roles(role, reason="Met criteria for role assignment (Season 2)")
                    successfully_assigned.append(user_id)
                except Exception as e:
                    print(f"DEBUG: Failed to assign role to {user_id}: {e}")

            # Build final response
            response = f"Successfully processed role assignment for season {season}.\n\n"

            if not eligible_users:
                response += "No eligible users found for Season 2 in the specified date range.\n\n"

            if not_in_server:
                response += "Users eligible but not in server:\n" + "\n".join(
                    [f"<@{user}>" for user in not_in_server]) + "\n\n"

            if successfully_assigned:
                response += "Users successfully assigned the role:\n" + "\n".join(
                    [f"<@{user}>" for user in successfully_assigned]) + "\n"


            await processing_message.edit(content=response)
            return

        # -------------------------
        #         SEASON 1
        # -------------------------
        elif season == 1:
            # Filter rows up to Week 49
            season_data = []
            for row in data:
                if 'Week' in row and row['Week'] and row['Week'].startswith("Week"):
                    try:
                        week_num = int(row['Week'].split()[1])
                        if week_num <= 49:
                            season_data.append(row)
                        else:
                            print(f"DEBUG: Row excluded (Week > 49) => {row}")
                    except ValueError:
                        print(f"DEBUG: Could not parse week => {row['Week']}")
                else:
                    print(f"DEBUG: Row missing or invalid 'Week' => {row}")

            # Gather Discord IDs
            discord_ids = []
            for row in season_data:
                if row.get('Discord'):
                    discord_ids.append(row['Discord'])



            # Convert to int where possible
            valid_ids = []
            for discord_id in discord_ids:
                try:
                    valid_ids.append(int(discord_id))
                except ValueError:
                    print(f"DEBUG: Invalid Discord ID => {discord_id}")



            # Count occurrences
            user_counts = Counter(valid_ids)

            # Eligible if user appears >= 2 times
            eligible_users = {user_id: count for user_id, count in user_counts.items() if count >= 2}


            not_in_server = []
            successfully_assigned = []

            # Assign roles
            for user_id in eligible_users:
                member = ctx.guild.get_member(user_id)
                if not member:
                    not_in_server.append(user_id)
                    continue

                if role in member.roles:
                    continue

                try:
                    await member.add_roles(role, reason="Met criteria for role assignment (Season 1)")
                    successfully_assigned.append(user_id)
                except Exception as e:
                    print(f"DEBUG: Failed to assign role to {user_id} (Season 1): {e}")

            # Build final response
            response = f"Successfully assigned the role for season {season}.\n\n"

            if not eligible_users:
                response += "No eligible users found (2+ mentions up to Week 49).\n\n"

            if not_in_server:
                response += "Users eligible but not in server:\n" + "\n".join(
                    [f"<@{user}>" for user in not_in_server]) + "\n\n"

            if successfully_assigned:
                response += "Users successfully assigned the role:\n" + "\n".join(
                    [f"<@{user}>" for user in successfully_assigned]) + "\n"


            await processing_message.edit(content=response)
            return

        else:
            msg = f"I can't find Season {season} data in the sheet, sorry."
            await processing_message.edit(content=msg)

    except Exception as e:
        msg = f"An error occurred: {e}"
        await processing_message.edit(content=msg)



@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        # Handle missing argument error
        await ctx.send("You must provide the season number to use this command. For example: `!autoassign 1`.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have the required permissions to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Please provide a valid season number.")
    elif isinstance(error, commands.CommandNotFound):
        # Ignore CommandNotFound errors or handle them
        pass
    else:
        # Log unexpected errors with a short and custom message instead of a traceback
        print(f"[ERROR] An unexpected error occurred: {type(error).__name__} - {error}")


# on_message function to handle messages
@bot.event
async def on_message(message):
    # Ignore messages sent by the bot itself
    if message.author == bot.user:
        return

    # Check for trigger words and send the help embed if found
    if "commands?" in message.content.lower() or "command?" in message.content.lower():
        await handle_command_help(message)

    # Ensure other commands are still processed
    await bot.process_commands(message)


bot.run(os.getenv("TOKEN"))
