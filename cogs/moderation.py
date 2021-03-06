import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Union

import discord
from discord.ext.commands import command


class Moderation:
    def __init__(self, bot):
        self.bot = bot
        self.log_chan = bot.get_channel(413010299776532490)
        self.spamguard_blacklist = bot._spamguard_blacklist
        self.msg_num = 0
        self.embed_colors = {
            "kick": 0xffa500,
            "ban": 0xff0000,
            "warn": 0xffff00,
            "mute": 0xa52a2a,
            "unmute": 0x73dcff
        }
        self.converter = {
            "kick": "ed",
            "mute": "d",
            "ban": "ned",
            "warn": "ed",
            "unmute": "d"
        }

    async def __local_check(self, ctx):
        perms = ctx.author.guild_permissions
        return (perms.kick_members and perms.ban_members) or ctx.author.id == 111158853839654912

    async def log_action(self, ctx, action, *, member, reason=None, mod=None, minutes=None):
        _action = action
        if action in ('gag', 'sleep'):
            action = 'mute'
        embed = discord.Embed(title=f"Member {action}", description=reason)
        embed.color = self.embed_colors[action]
        embed.timestamp = datetime.now()

        embed.add_field(name="Moderator", value=mod)
        if minutes is not None:
            embed.add_field(name="Unmute in", value=str(minutes) + " minutes")
        embed.set_author(name=f"{member} / {member.id}", icon_url=member.avatar_url)
        embed.set_footer(text="Invoked in #" + ctx.channel.name)
        if ctx.guild.id == 391483719803994113:
            await self.log_chan.send(embed=embed)
        if self.bot.config[ctx.guild.id]['echo_mod_actions']:
            if _action == "sleep":
                await ctx.send(f"`{member}` has been put to sleep by {mod}.")
            else:
                action += self.converter[action]
                await ctx.send(f"`{member}` has been {action} by {mod}.")

    async def on_guild_channel_create(self, channel):
        if channel.guild.id in self.bot.muted_roles:
            r_id = self.bot.muted_roles[channel.guild.id]
            role = channel.guild.get_role(r_id)
            await channel.set_permissions(role, send_messages=False)

    async def handle_spamguard(self, ctx):
        if ctx.channel.id in self.spamguard_blacklist:
            return

        if ctx.message.attachments:
            past = datetime.utcnow() - timedelta(minutes=0.5)  # search back for half a min
            c = 0
            async for m in ctx.history(after=past):
                if m.attachments and m.author == ctx.author:
                    c += 1
                if c >= 4:  # too many images, max is 3
                    ctx.author = ctx.guild.me
                    state = self.bot.muted_members.get(ctx.author.id)
                    if state and state['muted']:
                        return
                    await ctx.invoke(self.bot.get_command("mute"), ctx.message.author,
                                     body=("Image / file spamming", 5))
                    return

    async def handle_scrambler(self, ctx):  # im not proud
        if ctx.channel.id != 391483720244264961:
            return
        self.msg_num += 1
        if self.msg_num >= 5000:
            self.msg_num = 0
            await ctx.invoke(self.bot.get_command("scramble"))

    async def on_message(self, message):
        if message.author.bot:
            return
        ctx = await self.bot.get_context(message)
        await self.handle_spamguard(ctx)
        await self.handle_scrambler(ctx)

    @command()  # this is actually horrid
    async def config(self, ctx):
        """Allows configuration of options for the server."""

        fmt = "Enter config number to toggle the value, or `x` to cancel:"
        config_index = {}
        try:
            config = self.bot.config[ctx.guild.id]
        except KeyError:
            query = """
                INSERT INTO config VALUES ($1, $2 ,$3)
                RETURNING *
            """
            r = await self.bot.pool.fetchrow(query, ctx.guild.id, False, False)
            r = dict(r)
            self.bot.config[r.pop('guild_id')] = r
            config = self.bot.config[ctx.guild.id]

        fmt += "```"
        for i, key in enumerate(config):
            fmt += f"\n{i+1}. [{key}] : {config[key]}"
            config_index[i + 1] = key
        fmt += "```"
        await ctx.send(fmt)
        try:
            def check(m):
                return (m.author == ctx.author) and (m.channel == ctx.channel)

            msg = await self.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send("Timeout.")
        if msg.content.lower() != 'x':
            config[config_index[int(msg.content)]] = not config[config_index[int(msg.content)]]
            query = """
                UPDATE config
                SET {} = {} WHERE guild_id = {}
            """.format(config_index[int(msg.content)], config[config_index[int(msg.content)]], ctx.guild.id)
            await self.bot.pool.execute(query)
            await ctx.send(config_index[int(msg.content)] + " toggled.")

    def _answer(arg):
        ret = None
        if arg.lower() in ['y', 'yes', 'true', 'on', 'enable']:
            ret = True
        elif arg.lower() in ['n', 'no', 'false', 'off', 'disable', 'stop']:
            ret = False
        return arg, ret

    @command()
    async def spamguard(self, ctx, state: _answer, channel: discord.TextChannel = None):
        """Sets the state of the spamguard for a channel.

        If no channel specified, defaults to current channel.
        """

        answer, state = state
        channel = channel or ctx.channel
        if state is None:
            return await ctx.send(f"❗`{answer}` is not a valid argument! "
                                  "Try something like: yes, no, true, false, on, off.`")

        elif state:  # ENABLE
            msg = f"Successfully enabled the spamguard in {channel.mention}."
            if channel.id not in self.spamguard_blacklist:
                return await ctx.send(msg)

            query = """
                DELETE FROM spamguard_blacklist WHERE channel_id = $1
            """
            await self.bot.pool.execute(query, channel.id)
            self.spamguard_blacklist.remove(channel.id)
            await ctx.send(msg)

        else:  # DISABLE
            msg = f"Successfully disabled the spamguard in {channel.mention}."
            if channel.id in self.spamguard_blacklist:
                return await ctx.send(msg)

            query = """
                INSERT INTO spamguard_blacklist (channel_id) VALUES ($1)
            """
            await self.bot.pool.execute(query, channel.id)
            self.spamguard_blacklist.append(channel.id)
            await ctx.send(msg)

    @command()
    async def lock(self, ctx):
        """Locks down the current channel."""

        await ctx.message.delete()
        msg = await ctx.send("This channel is now under lockdown!")
        perms = ctx.channel.overwrites_for(ctx.guild.default_role)

        query = """
            INSERT INTO lockdown (channel_id, message_id, perms) VALUES ($1, $2, $3)
        """
        await self.bot.pool.execute(query, ctx.channel.id, msg.id, json.dumps(perms._values))

        perms.send_messages = False
        perms.add_reactions = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=perms)

    @command()
    async def unlock(self, ctx):
        """Releases the current channel from lockdown."""

        await ctx.message.delete()
        query = """
            DELETE FROM lockdown WHERE channel_id=$1 RETURNING *
        """
        recs = await self.bot.pool.fetchrow(query, ctx.channel.id)
        if not recs:
            return

        channel_id, msg_id, perms = recs
        msg = await self.bot.get_channel(channel_id).get_message(msg_id)
        await msg.delete()

        perms = discord.PermissionOverwrite(**json.loads(perms))
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=perms)
        await ctx.send("This channel is no longer under lockdown.", delete_after=10)

    @command()
    async def kick(self, ctx, target: discord.Member, *, reason=None):
        """Kicks a member."""

        await ctx.message.delete()
        await target.kick(reason=f"{ctx.author.name}: {reason}")

        query = """
            INSERT INTO kicks (guild_id, member_id, channel_id, moderator_id, reason, action_time)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        await self.bot.pool.execute(query, ctx.guild.id, target.id, ctx.channel.id,
                                    ctx.author.id, reason, datetime.utcnow())

        await self.log_action(ctx, "kick", member=target, reason=reason, mod=ctx.author)

    @command(aliases=['dab'])
    async def ban(self, ctx, target: discord.Member, *, reason=None):
        """Bans a member."""

        await ctx.message.delete()
        await target.ban(reason=f"{ctx.author.name}: {reason}", delete_message_days=0)

        query = """
            INSERT INTO bans (guild_id, member_id, channel_id, moderator_id, reason, action_time)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        await self.bot.pool.execute(query, ctx.guild.id, target.id, ctx.channel.id,
                                    ctx.author.id, reason, datetime.utcnow())

        await self.log_action(ctx, "ban", member=target, reason=reason, mod=ctx.author)

    def parse_mute(arg):
        if arg is None:
            return None, None
        if len(arg.split(' ', 1)) == 1:
            maybe_time = arg.split(' ', 1)[0]
            reason = None
        else:
            maybe_time, reason = arg.split(' ', 1)
        pattern = r"(?:(?P<hours>\d+)h)?(?P<minutes>\d+)m"
        m = re.match(pattern, maybe_time)
        if m is None:
            return arg, None
        minutes, hours = m.group('minutes', 'hours')
        if hours is None:
            return reason, int(minutes)
        return reason, int(minutes) + int(hours) * 60

    @command(aliases=['gag', 'sleep'], usage="<target> [time] [reason]")
    async def mute(self, ctx, target: discord.Member, *, body: parse_mute = None):
        """Mutes a member. The reason will be sent as a notice to said member in a DM."""

        if body is None:
            reason, minutes = None, None
        else:
            reason, minutes = body
        await ctx.message.delete()
        r_id = self.bot.muted_roles.get(ctx.guild.id)
        if not r_id:
            role = await ctx.guild.create_role(name="Muted")
            r_id = role.id
            self.bot.muted_roles[ctx.guild.id] = r_id
            for c in ctx.guild.text_channels:
                await c.set_permissions(role, send_messages=False)

            query = """
                INSERT INTO mute_roles (guild_id, role_id) VALUES ($1, $2)
            """
            await self.bot.pool.execute(query, ctx.guild.id, role.id)

        role = ctx.guild.get_role(r_id)
        await target.add_roles(role)

        timeout = datetime.utcnow() + timedelta(minutes=minutes) if minutes else None
        log_query = """
            INSERT INTO mutes (guild_id, member_id, channel_id, moderator_id, reason, action_time)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        await self.bot.pool.execute(log_query, ctx.guild.id, target.id, ctx.channel.id,
                                    ctx.author.id, reason, datetime.utcnow())

        query = """
            INSERT INTO mute_states (member_id, guild_id, muted, mute_timeout, muter_id)
            VALUES ($1, $2, true, $3, $4)
            ON CONFLICT (guild_id, member_id) DO UPDATE
                SET muted = true,
                    mute_timeout = $3,
                    muter_id = $4
            RETURNING *
        """
        rec = await self.bot.pool.fetchrow(query, target.id, ctx.guild.id, timeout, ctx.author.id)

        self.bot.muted_members[target.id] = dict(rec)
        self.bot.loop.create_task(self.bot.ensure_unmute(target.id, self.bot.muted_members[target.id]))

        fmt = f"You've been muted by {ctx.author}!"
        if minutes is not None:
            fmt += f"\nMute duration: {minutes} minute(s)"
        if reason:
            fmt += f"\nReason: \"{reason}\""

        try:
            await target.send(fmt)
        except:  # noqa
            try:
                await ctx.author.send(f"Could not send mute notice to `{target}`.\n"
                                      "They may have DMs disabled, or have blocked me.\n\n"
                                      f"Mute Reason:\n{reason}")
            except:  # noqa
                pass
        await self.log_action(ctx, ctx.invoked_with, member=target, reason=reason, mod=ctx.author, minutes=minutes)

    async def _do_unmute(self, target, *, reason, mod, guild):
        r_id = self.bot.muted_roles[guild.id]
        if r_id:
            role = guild.get_role(r_id)
            if role:
                if role not in target.roles:
                    return
                await target.remove_roles(role)
                query = """
                    UPDATE mute_states
                        SET muted = false,
                            mute_timeout = NULL,
                            muter_id = NULL
                        WHERE guild_id = $1 AND member_id = $2
                    RETURNING *
                """
                rec = await self.bot.pool.fetchrow(query, guild.id, target.id)
                self.bot.muted_members[target.id] = dict(rec)

        fmt = f"You've been unmuted by {mod}!"
        if reason:
            fmt += f"\nReason: \"{reason}\""

        try:
            await target.send(fmt)
        except:  # noqa
            try:
                await mod.send(f"Could not send unmute notice to `{target}`.\n"
                               "They may have DMs disabled, or have blocked me.\n\n"
                               f"Unmute Reason:\n{reason}")
            except:  # noqa
                pass

    @command(aliases=['ungag'])
    async def unmute(self, ctx, target: discord.Member, *, reason=None):
        """Unmutes a member. The reason will be sent as a notice to said member in a DM."""
        try:
            await ctx.message.delete()
        except:  # noqa
            pass
        await self._do_unmute(target, reason=reason, mod=ctx.author, guild=ctx.guild)
        await self.log_action(ctx, "unmute", member=target, reason=reason, mod=ctx.author)

    @command()
    async def warn(self, ctx, target: discord.Member, *, warning=None):
        """Warns a member. The warning will be sent to said member in a DM."""

        await ctx.message.delete()
        try:
            if warning is None:
                await target.send(f"You've received a warning from {ctx.author}!")
            else:
                await target.send(f"You've received a warning from {ctx.author}:\n \"{warning}\"")
        except:  # noqa
            try:
                await ctx.author.send(f"Could not send a warning to `{target}`.\n"
                                      "They may have DMs disabled, or have blocked me.\n\n"
                                      f"Warning text was:\n{warning}")
            except:  # noqa
                pass

        query = """
            INSERT INTO warnings (guild_id, member_id, reason, moderator_id, action_time, channel_id)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        await self.bot.pool.execute(query, ctx.guild.id, target.id, warning,
                                    ctx.author.id, datetime.utcnow(), ctx.channel.id)

        await self.log_action(ctx, "warn", member=target, reason=warning, mod=ctx.author)

    @command(aliases=['prune', 'p'])
    async def purge(self, ctx, count: int, *users: discord.Member):
        """Deletes messages en masse."""

        await ctx.message.delete()
        if count > 100:
            await ctx.send(f"You are about to purge {count}. Are you sure you want to purge these many messages? (y/n)")

            def check(m):
                (m.content.lower() == 'y' or m.content.lower() == 'n') and m.author == ctx.message.author
            try:
                reply = await self.bot.wait_for("message", check=check, timeout=10)
            except asyncio.TimeoutError:
                return await ctx.send("Cancelled purge.")
            if not reply or reply.content.lower().strip() == 'n':
                return await ctx.send("Cancelled purge.")
            else:
                await ctx.message.delete()
        try:
            await ctx.channel.purge(limit=count, check=lambda message: message.author in users if users else True)
        except discord.HTTPException:
            await ctx.send("Something went wrong! Could not purge.")

    @command()
    async def check(self, ctx, target: Union[discord.Member, int], action_type="overall"):
        """Shows the list of previous warnings a member has been given."""

        if action_type == "overall":
            return await self.overall_check(ctx, target)

        types = {
            'warnings': 'warnings',
            'warning': 'warnings',
            'warn': 'warnings',
            'bans': 'bans',
            'ban': 'bans',
            'kicks': 'kicks',
            'kick': 'kicks',
            'mutes': 'mutes',
            'mute': 'mutes'
        }
        if action_type not in types.keys():
            return await ctx.send(f"Couldnt find that action type! I log: {', '.join(set(types.values()))}.\n"
                                  "You may also omit the type, and I'll show you overall info about the member.")

        query = f"""
            SELECT * FROM {types[action_type]}
            WHERE guild_id = $1 AND member_id = $2
        """
        t_id = target if isinstance(target, int) else target.id
        recs = await self.bot.pool.fetch(query, ctx.guild.id, t_id)
        txt = types[action_type] + " list:\n"
        for r in recs:
            mod = ctx.guild.get_member(r['moderator_id'])
            channel = ctx.guild.get_channel(r['channel_id'])
            warning = r['reason']
            timestamp = r['action_time']
            time_fmt = datetime.strftime(timestamp, r"%H:%M %h %d %Y")
            fmt = f"**MOD**: {mod}\n**TARGET**: {target}\n**REASON**: {warning}\n**AT**: {time_fmt}\n**IN**: {'#' + channel.name if channel else 'NULL'}\n{'-' * 10}\n"  # noqa: E226, E501
            txt += fmt
        if txt:
            if len(txt) >= 2000:
                haste = await self.bot.make_haste(txt, raw=True)
                return await ctx.send(haste)
            await ctx.send(txt)
        else:
            await ctx.send("No warnings for " + str(target))

    async def overall_check(self, ctx, target):
        query = """
            SELECT
            (
                SELECT count(*) FROM mutes
                WHERE member_id = $1
            ) AS mute_count,
            (
                SELECT count(*) FROM bans
                WHERE member_id = $1
            ) AS ban_count,
            (
                SELECT count(*) FROM kicks
                WHERE member_id = $1
            ) AS kick_count,
            (
                SELECT count(*) FROM warnings
                WHERE member_id = $1
            ) AS warning_count
        """
        t_id = target if isinstance(target, int) else target.id
        rec = await self.bot.pool.fetchrow(query, t_id)
        mutes = rec['mute_count']
        bans = rec['ban_count']
        kicks = rec['kick_count']
        warnings = rec['warning_count']
        description = 'For more info on each field, do `>check Target#1234 field`.\n' \
                      f'For example, `>check {target} bans`'
        embed = discord.Embed(title=f"Moderation stats", description=description) \
            .add_field(name="Total Warnings", value=warnings, inline=False) \
            .add_field(name="Total Mutes", value=mutes, inline=False) \
            .add_field(name="Total Kicks", value=kicks, inline=False) \
            .add_field(name="Total Bans", value=bans, inline=False) \
            .set_author(name=f"{target} / {t_id}")
        if not isinstance(target, int):
            embed.author.icon_url = target.avatar_url
        await ctx.send(embed=embed)

    @command()
    async def lookup(self, ctx, member: discord.Member):
        """Show a list of a member's previous usernames."""
        query = """
            SELECT usernames FROM usernames WHERE member_id = $1
        """
        r = await self.bot.pool.fetchrow(query, member.id)
        to_send = "Known Usernames:\n"
        if r is None:
            await ctx.send(to_send + member.name)
        else:
            fmt = ""
            for name in r['usernames']:
                fmt += name + "\n"
            if len(fmt) >= 2000:
                url = await self.bot.make_haste(fmt)
                await ctx.send(to_send + url)
            else:
                await ctx.send(to_send + fmt)

    @command()
    async def remove(self, ctx, member: discord.Member, role: discord.Role):
        await ctx.message.delete()
        await member.remove_roles(role)
        if self.bot.config[ctx.guild.id]['echo_mod_actions']:
            await ctx.send(f"Role `{role}` has been removed from `{member}` by `{ctx.author}`.")


def setup(bot):
    bot.add_cog(Moderation(bot))
