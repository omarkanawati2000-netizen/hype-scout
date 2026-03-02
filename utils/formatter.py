"""
utils/formatter.py — Alert formatting for Discord (markdown) and Telegram (HTML)
"""
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_usd(val: float) -> str:
    val = val or 0
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    elif val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.0f}"


def tier_emoji(mult: float) -> str:
    if mult >= 10: return "💥"
    if mult >= 5:  return "🔥"
    if mult >= 3:  return "⚡"
    return "🚀"


def age_status_emoji(age_minutes: float) -> str:
    if age_minutes < 2:  return "🟢"
    if age_minutes < 5:  return "🟡"
    return "🔴"


def bc_bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def holder_badge(holders: int) -> str:
    if holders < 20:  return "🐋 WHALE"
    if holders < 100: return "🔒 SOLID"
    return "🌐 DIST"


# ── Discord Alert ─────────────────────────────────────────────────────────────

def format_discord_alert(d: dict) -> str:
    mint    = d.get("mint", "")
    name    = d.get("name", "?")
    symbol  = d.get("symbol", "?")
    mc      = d.get("market_cap", 0)
    ath     = d.get("ath_market_cap", mc)
    liq     = d.get("liquidity_usd", 0)
    age     = d.get("age_minutes", 0)
    bc_pct  = d.get("bonding_curve_progress", 0)
    twitter = d.get("twitter") or ""
    vol_1h  = d.get("vol_h1") or d.get("vol_1h") or 0
    vol_m5  = d.get("vol_m5", 0) or 0
    buys_h1 = d.get("buys_h1", 0) or 0
    sells_h1 = d.get("sells_h1", 0) or 0
    holders = d.get("holder_count") or 0

    age_str = "<1m" if age < 1 else f"{age:.0f}m"
    status  = age_status_emoji(age)

    dex_url  = f"https://dexscreener.com/solana/{mint}"
    pump_url = f"https://pump.fun/{mint}"

    if twitter:
        links = f"[𝕏]({twitter}) • [Chart]({dex_url}) • [Pump]({pump_url})"
    else:
        links = f"[Chart]({dex_url}) • [Pump]({pump_url})"

    holder_line = ""
    if holders:
        holder_line = f"👥 Hodls: **{holders}** {holder_badge(holders)}\n"

    vol_line = f"📊 Vol 1h: **{fmt_usd(vol_1h)}**"
    if vol_1h > 0:
        vol_line += f" | 🟢{buys_h1} 🔴{sells_h1}"
    vol_line += "\n"
    if vol_m5 > 0:
        vol_line += f"⚡ Vol 5m: **{fmt_usd(vol_m5)}**\n"

    return (
        f"🔥 **{name}** | PumpScanner\n"
        f"⏰ Age: {age_str} | {status}\n"
        f"🔗 {links}\n"
        f"💰 MC: {fmt_usd(mc)} • 🏆 ATH {fmt_usd(ath)}\n"
        f"💧 Liq: {fmt_usd(liq)}\n"
        f"{vol_line}"
        f"{holder_line}"
        f"🧪 BC: {bc_pct:.0f}%\n"
        f"👨‍💻 Dev: 0.0 SOL | 0.0% ${symbol}\n\n"
        f"`{mint}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Telegram Alert (HTML) ─────────────────────────────────────────────────────

def format_telegram_alert(d: dict) -> str:
    mint    = d.get("mint", "")
    name    = d.get("name", "?")
    symbol  = d.get("symbol", "?")
    mc      = d.get("market_cap", 0)
    ath     = d.get("ath_market_cap", mc)
    liq     = d.get("liquidity_usd", 0)
    age     = d.get("age_minutes", 0)
    bc_pct  = d.get("bonding_curve_progress", 0)
    twitter = d.get("twitter") or ""
    vol_1h  = d.get("vol_h1") or d.get("vol_1h") or 0
    vol_m5  = d.get("vol_m5", 0) or 0
    buys_h1 = d.get("buys_h1", 0) or 0
    sells_h1 = d.get("sells_h1", 0) or 0
    holders = d.get("holder_count") or 0

    age_str = "&lt;1m" if age < 1 else f"{age:.0f}m"
    status  = age_status_emoji(age)

    dex_url  = f"https://dexscreener.com/solana/{mint}"
    pump_url = f"https://pump.fun/{mint}"

    links_parts = []
    if twitter:
        links_parts.append(f'<a href="{twitter}">𝕏</a>')
    links_parts.append(f'<a href="{dex_url}">Chart</a>')
    links_parts.append(f'<a href="{pump_url}">Pump</a>')
    links = " • ".join(links_parts)

    holder_line = ""
    if holders:
        holder_line = f"👥 Hodls: <b>{holders}</b> {holder_badge(holders)}\n"

    vol_line = f"📊 Vol 1h: <b>{fmt_usd(vol_1h)}</b>"
    if vol_1h > 0:
        vol_line += f" | 🟢{buys_h1} 🔴{sells_h1}"
    vol_line += "\n"
    if vol_m5 > 0:
        vol_line += f"⚡ Vol 5m: <b>{fmt_usd(vol_m5)}</b>\n"

    return (
        f"🔥 <b>{name}</b> | PumpScanner\n"
        f"⏰ Age: {age_str} | {status}\n"
        f"🔗 {links}\n"
        f"💰 MC: {fmt_usd(mc)} • 🏆 ATH {fmt_usd(ath)}\n"
        f"💧 Liq: {fmt_usd(liq)}\n"
        f"{vol_line}"
        f"{holder_line}"
        f"🧪 BC: {bc_pct:.0f}%\n"
        f"👨‍💻 Dev: 0.0 SOL | 0.0% ${symbol}\n\n"
        f"<code>{mint}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Single Runner Alert (new format) ──────────────────────────────────────────

def _money_bags(mult: float) -> str:
    """Scale 💸 emoji count with actual multiplier."""
    if mult >= 20: return "💸" * 16
    if mult >= 10: return "💸" * 12
    if mult >= 5:  return "💸" * 8
    if mult >= 3:  return "💸" * 6
    return "💸" * 4


def format_single_runner(r: dict, platform: str = "discord") -> str:
    """
    Format a single-coin runner alert in the clean pump style.

    📈 COIN is up 3X 📈
    from ⚡ Entry Signal

    $50.7K —> $150K 💵

    💸💸💸💸💸💸

    [Chart] · [Pump]
    """
    name            = r.get("name", r.get("symbol", "?"))
    thresh          = r.get("thresh", 2.0)
    mult            = r.get("mult", thresh)
    entry_mc        = r.get("entry_mc", 0)
    current_mc      = r.get("current_mc", 0)
    mint            = r.get("mint", "")
    discord_msg_id  = r.get("discord_msg_id")
    telegram_msg_id = r.get("telegram_msg_id")

    mult_display = f"{mult:.1f}".rstrip('0').rstrip('.')
    bags         = _money_bags(mult)
    mc_arrow     = f"{fmt_usd(entry_mc)} —> {fmt_usd(current_mc)}"
    dex_url      = f"https://dexscreener.com/solana/{mint}"
    pump_url     = f"https://pump.fun/{mint}"

    # Telegram channel jump link: t.me/c/{channel_numeric_id}/{msg_id}
    TG_CHANNEL_NUMERIC = "3816610028"   # from TELEGRAM_CHANNEL_ID -1003816610028
    # Discord jump link
    GUILD_ID   = "1468193294432604326"
    DISCORD_CH = "1477161564460159097"

    if platform == "telegram":
        if telegram_msg_id:
            tg_jump = f"https://t.me/c/{TG_CHANNEL_NUMERIC}/{telegram_msg_id}"
            signal_line = f'from <a href="{tg_jump}">⚡ PumpScanner Signal</a>'
        else:
            signal_line = "from ⚡ PumpScanner Signal"
        return (
            f"📈 <b>{name}</b> is up <b>{mult_display}X</b> 📈\n"
            f"{signal_line}\n"
            f"\n"
            f"{mc_arrow} 💵\n"
            f"\n"
            f"{bags}\n"
            f"\n"
            f"<code>{mint}</code>\n"
            f"\n"
            f'<a href="{dex_url}">Chart</a> · <a href="{pump_url}">Pump</a>'
        )
    else:  # discord
        if discord_msg_id:
            dc_jump     = f"https://discord.com/channels/{GUILD_ID}/{DISCORD_CH}/{discord_msg_id}"
            signal_line = f"from [⚡ PumpScanner Signal](<{dc_jump}>)"
        else:
            signal_line = "from ⚡ PumpScanner Signal"
        return (
            f"📈 **{name}** is up **{mult_display}X** 📈\n"
            f"{signal_line}\n"
            f"\n"
            f"{mc_arrow} 💵\n"
            f"\n"
            f"{bags}\n"
            f"\n"
            f"`{mint}`\n"
            f"\n"
            f"[Chart](<{dex_url}>) · [Pump](<{pump_url}>)"
        )


# ── Runner Messages ────────────────────────────────────────────────────────────

def format_runner_msg(runners: list, platform: str = "discord") -> str:
    """Format a list of runner dicts into a multi-coin pump alert."""
    count = len(runners)
    noun = "runner" if count == 1 else "runners"
    now = datetime.now().strftime("%H:%M")

    if platform == "telegram":
        lines = [f"🔴 <b>PumpScanner Live Runners</b> · {count} active {noun} · {now}", "━━━━━━━━━━━━━━━━━━━━━━"]
        for r in runners:
            emoji = tier_emoji(r["mult"])
            dex_url  = f"https://dexscreener.com/solana/{r['mint']}"
            pump_url = f"https://pump.fun/{r['mint']}"
            lines.append(
                f"{emoji} <b>{r['name']}</b> is up <b>{r['mult']}x</b> from entry\n"
                f"    {fmt_usd(r['entry_mc'])} → <b>{fmt_usd(r['current_mc'])}</b> | 💧 {fmt_usd(r.get('liq', 0))}\n"
                f"    📊 Vol: {fmt_usd(r.get('vol_h1', 0))} | 🟢{r.get('buys_h1', 0)} 🔴{r.get('sells_h1', 0)}\n"
                f"    <a href=\"{dex_url}\">Chart</a> · <a href=\"{pump_url}\">Pump</a>"
            )
    else:  # discord
        lines = [f"🔴 **PumpScanner Live Runners** · {count} active {noun} · {now}", "━━━━━━━━━━━━━━━━━━━━━━"]
        for r in runners:
            emoji = tier_emoji(r["mult"])
            mint = r["mint"]
            dex_url  = f"https://dexscreener.com/solana/{mint}"
            pump_url = f"https://pump.fun/{mint}"
            lines.append(
                f"{emoji} **{r['name']}** is up **{r['mult']}x** from entry\n"
                f"    {fmt_usd(r['entry_mc'])} → **{fmt_usd(r['current_mc'])}** | 💧 {fmt_usd(r.get('liq', 0))} | 📊 Vol: {fmt_usd(r.get('vol_h1', 0))}\n"
                f"    🟢 {r.get('buys_h1', 0)} / 🔴 {r.get('sells_h1', 0)} · "
                f"[Chart](<{dex_url}>) · [Pump](<{pump_url}>)"
            )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def _leaderboard_timestamp() -> str:
    """Return a clean, timezone-aware timestamp string for the leaderboard header."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/Denver"))
        tz_abbr = now.strftime("%Z")  # MST or MDT
    except Exception:
        now = datetime.now()
        tz_abbr = "MT"
    # Windows-safe: strip leading zeros manually
    month = now.strftime("%b")
    day   = str(now.day)
    year  = now.strftime("%Y")
    hour  = str(now.hour % 12 or 12)
    mins  = now.strftime("%M")
    ampm  = now.strftime("%p")
    return f"{month} {day}, {year} · {hour}:{mins} {ampm} {tz_abbr}"


def _fmt_age_str(age_str: str) -> str:
    """Convert ISO date string like '2026-03-01' to 'Mar 1'."""
    try:
        d = datetime.strptime(age_str[:10], "%Y-%m-%d")
        return f"{d.strftime('%b')} {d.day}"
    except Exception:
        return age_str[:10]


def format_leaderboard(coins: list, platform: str = "discord") -> str:
    """Format leaderboard top N coins."""
    medal = ["🥇", "🥈", "🥉"]
    now   = _leaderboard_timestamp()

    GUILD_ID           = "1468193294432604326"
    DISCORD_ALERT_CH   = "1477161564460159097"
    TG_CHANNEL_NUMERIC = "3816610028"

    if platform == "telegram":
        lines = [f"🏆 <b>PumpScanner Leaderboard</b> · Top {len(coins)} · {now}", "━━━━━━━━━━━━━━━━━━━━━━"]
        for i, c in enumerate(coins):
            rank   = medal[i] if i < 3 else f"#{i+1}"
            emoji  = tier_emoji(c["peak_mult"])
            mint   = c.get("mint", "")
            tg_mid = c.get("telegram_msg_id")
            age    = _fmt_age_str(c.get("age_str", ""))
            name   = c['name']

            # Make the coin name itself the clickable link to the original scan
            if tg_mid:
                name_link = f'<a href="https://t.me/c/{TG_CHANNEL_NUMERIC}/{tg_mid}">{name}</a>'
            else:
                name_link = f'<a href="https://pump.fun/{mint}">{name}</a>'

            lines.append(
                f"{rank} {emoji} {name_link} — <b>{c['peak_mult']:.1f}x</b>\n"
                f"    {fmt_usd(c['entry_mc'])} → {fmt_usd(c['peak_mc'])} · {age}"
            )
    else:
        lines = [f"🏆 **PumpScanner Leaderboard** · Top {len(coins)} · {now}", "━━━━━━━━━━━━━━━━━━━━━━"]
        for i, c in enumerate(coins):
            rank    = medal[i] if i < 3 else f"#{i+1}"
            emoji   = tier_emoji(c["peak_mult"])
            mint    = c.get("mint", "")
            dc_mid  = c.get("discord_msg_id")
            dex_url = f"https://dexscreener.com/solana/{mint}"
            if dc_mid:
                jump_url   = f"https://discord.com/channels/{GUILD_ID}/{DISCORD_ALERT_CH}/{dc_mid}"
                alert_link = f"[Alert](<{jump_url}>) · [Chart](<{dex_url}>)"
            else:
                alert_link = f"[Chart](<{dex_url}>)"
            lines.append(
                f"{rank} {emoji} **{c['name']}** — **{c['peak_mult']:.1f}x** "
                f"({fmt_usd(c['entry_mc'])} → {fmt_usd(c['peak_mc'])}) "
                f"{alert_link}"
            )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
