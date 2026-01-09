"""Email module using SendGrid for sending watchlist emails."""

import logging
from datetime import datetime

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Content, MimeType

from app.config import get_settings
from app.time_gate import format_chicago_timestamp, get_today_date_str

logger = logging.getLogger(__name__)

DISCLAIMER = """
<p style="font-size: 11px; color: #888; margin-top: 30px; border-top: 1px solid #ddd; padding-top: 15px;">
<strong>DISCLAIMER:</strong> This watchlist is for informational purposes only and does not constitute 
investment advice. Trading stocks involves risk, and you may lose money. Past performance is not 
indicative of future results. Always do your own research and consider your risk tolerance before 
making any trades. The author is not a licensed financial advisor.
</p>
"""


def format_pick_html(pick: dict, index: int) -> str:
    """Format a single pick as HTML with position sizing."""
    symbol = pick.get("symbol", "N/A")
    last = pick.get("last", 0)
    pct_change = pick.get("pct_change", 0)
    volume = pick.get("volume_so_far", 0)
    rvol = pick.get("rvol", 0)
    vwap = pick.get("vwap", 0)
    above_vwap = pick.get("above_vwap", False)
    hod = pick.get("hod", 0)
    near_hod = pick.get("near_hod", 0)
    atr = pick.get("atr_1m", 0)
    score = pick.get("score", 0)

    levels = pick.get("levels", {})
    setup_type = levels.get("setup_type", "N/A") if levels else "N/A"
    buy_area = levels.get("buy_area") if levels else None
    stop = levels.get("stop") if levels else None
    t1 = levels.get("target_1") if levels else None
    t2 = levels.get("target_2") if levels else None
    t3 = levels.get("target_3") if levels else None
    explanation = levels.get("explanation", "") if levels else ""
    risk_flags = levels.get("risk_flags", []) if levels else []
    
    # Position sizing data
    position = pick.get("position", {})
    shares = position.get("shares", 0) if position else 0
    total_risk = position.get("total_risk", 0) if position else 0
    profit_t1 = position.get("profit_t1", 0) if position else 0
    profit_t2 = position.get("profit_t2", 0) if position else 0
    profit_t3 = position.get("profit_t3") if position else None
    meets_goal = position.get("meets_daily_goal", False) if position else False
    capital = position.get("capital", 0) if position else 0

    # Color coding
    change_color = "#22c55e" if pct_change >= 0 else "#ef4444"
    vwap_status = "Above" if above_vwap else "Below"
    vwap_color = "#22c55e" if above_vwap else "#ef4444"
    goal_badge = '<span style="background: #22c55e; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; margin-left: 8px;">✓ MEETS GOAL</span>' if meets_goal else ""

    # Format buy area
    buy_area_str = (
        f"${buy_area[0]:.2f} - ${buy_area[1]:.2f}"
        if buy_area
        else "N/A"
    )

    # Format targets with dollar amounts
    targets_html = ""
    if t1:
        targets_html += f'<div><strong>T1:</strong> ${t1:.2f} <span style="color: #22c55e;">(+${profit_t1:.2f})</span></div>'
    if t2:
        targets_html += f'<div><strong>T2:</strong> ${t2:.2f} <span style="color: #22c55e;">(+${profit_t2:.2f})</span></div>'
    if t3 and profit_t3:
        targets_html += f'<div><strong>T3:</strong> ${t3:.2f} <span style="color: #22c55e;">(+${profit_t3:.2f})</span></div>'
    elif t3:
        targets_html += f'<div><strong>T3:</strong> ${t3:.2f}</div>'
    if not targets_html:
        targets_html = "<div>N/A</div>"

    # Risk flags badges
    flags_html = ""
    if risk_flags:
        flag_badges = " ".join(
            f'<span style="background: #fef3c7; color: #92400e; padding: 2px 6px; '
            f'border-radius: 3px; font-size: 10px; margin-right: 4px;">{flag}</span>'
            for flag in risk_flags
        )
        flags_html = f'<div style="margin-top: 8px;">{flag_badges}</div>'
    
    # Position sizing section
    position_html = ""
    if position and shares > 0:
        position_html = f"""
        <div style="background: #ecfdf5; border: 1px solid #10b981; border-radius: 6px; padding: 12px; margin-top: 12px;">
            <div style="font-weight: 600; color: #065f46; margin-bottom: 8px;">
                📐 Position Sizing (${capital:,.0f} capital) {goal_badge}
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; font-size: 13px;">
                <div><strong>Shares:</strong> {shares}</div>
                <div><strong>Risk:</strong> <span style="color: #dc2626;">${total_risk:.2f}</span></div>
                <div><strong>T1 Profit:</strong> <span style="color: #059669;">${profit_t1:.2f}</span></div>
            </div>
        </div>
        """

    return f"""
    <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px; background: #fafafa;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div>
                <span style="font-size: 24px; font-weight: bold; color: #1f2937;">#{index + 1} {symbol}</span>
                <span style="font-size: 18px; color: #6b7280; margin-left: 12px;">${last:.2f}</span>
                <span style="font-size: 16px; color: {change_color}; margin-left: 8px;">
                    {'+' if pct_change >= 0 else ''}{pct_change:.2f}%
                </span>
            </div>
            <div style="text-align: right;">
                <span style="background: #3b82f6; color: white; padding: 4px 10px; border-radius: 4px; font-size: 12px;">
                    Score: {score:.2f}
                </span>
            </div>
        </div>
        
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; font-size: 13px;">
            <div><strong>Volume:</strong> {volume:,}</div>
            <div><strong>RVOL:</strong> {rvol:.1f}x</div>
            <div><strong>VWAP:</strong> ${vwap:.2f} <span style="color: {vwap_color};">({vwap_status})</span></div>
            <div><strong>Near HOD:</strong> {near_hod:.1%}</div>
        </div>
        
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px; font-size: 13px;">
            <div><strong>HOD:</strong> ${hod:.2f}</div>
            <div><strong>ATR (1m):</strong> ${atr:.4f}</div>
            <div><strong>Setup:</strong> <span style="color: #7c3aed; font-weight: 600;">{setup_type}</span></div>
        </div>
        
        <div style="background: #f3f4f6; border-radius: 6px; padding: 12px; margin-top: 12px;">
            <div style="font-weight: 600; color: #374151; margin-bottom: 8px;">Trade Levels</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr 2fr; gap: 8px; font-size: 13px;">
                <div><strong style="color: #059669;">BUY AREA:</strong><br>{buy_area_str}</div>
                <div><strong style="color: #dc2626;">STOP:</strong><br>{"${:.2f}".format(stop) if stop else "N/A"}</div>
                <div><strong style="color: #2563eb;">TARGETS:</strong><br>{targets_html}</div>
            </div>
        </div>
        
        {position_html}
        
        <div style="font-size: 12px; color: #6b7280; margin-top: 10px; font-style: italic;">
            {explanation}
        </div>
        
        {flags_html}
    </div>
    """


def format_leaderboard_html(leaderboard: list[dict]) -> str:
    """Format leaderboard as HTML table."""
    rows = ""
    for entry in leaderboard:
        rank = entry.get("rank", 0)
        symbol = entry.get("symbol", "")
        score = entry.get("score", 0)
        pct_change = entry.get("pct_change", 0)
        rvol = entry.get("rvol", 0)
        near_hod = entry.get("near_hod", 0)
        above_vwap = entry.get("above_vwap", False)

        change_color = "#22c55e" if pct_change >= 0 else "#ef4444"
        vwap_icon = "✓" if above_vwap else "✗"
        vwap_color = "#22c55e" if above_vwap else "#ef4444"

        rows += f"""
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 8px; text-align: center;">{rank}</td>
            <td style="padding: 8px; font-weight: 600;">{symbol}</td>
            <td style="padding: 8px; text-align: center;">{score:.3f}</td>
            <td style="padding: 8px; text-align: center; color: {change_color};">
                {'+' if pct_change >= 0 else ''}{pct_change:.2f}%
            </td>
            <td style="padding: 8px; text-align: center;">{rvol:.1f}x</td>
            <td style="padding: 8px; text-align: center;">{near_hod:.1%}</td>
            <td style="padding: 8px; text-align: center; color: {vwap_color};">{vwap_icon}</td>
        </tr>
        """

    return f"""
    <div style="margin-top: 30px;">
        <h2 style="color: #1f2937; border-bottom: 2px solid #3b82f6; padding-bottom: 8px;">
            Top 10 Leaderboard
        </h2>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="background: #f3f4f6;">
                    <th style="padding: 10px; text-align: center;">Rank</th>
                    <th style="padding: 10px; text-align: left;">Symbol</th>
                    <th style="padding: 10px; text-align: center;">Score</th>
                    <th style="padding: 10px; text-align: center;">% Chg</th>
                    <th style="padding: 10px; text-align: center;">RVOL</th>
                    <th style="padding: 10px; text-align: center;">Near HOD</th>
                    <th style="padding: 10px; text-align: center;">VWAP</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    """


def format_email_body(
    picks: list[dict],
    leaderboard: list[dict],
    run_meta: dict,
) -> str:
    """
    Format the full email body as HTML.

    Args:
        picks: List of pick dicts with levels
        leaderboard: Top 10 leaderboard entries
        run_meta: Run metadata (timestamp, provider, etc.)

    Returns:
        HTML string for email body
    """
    timestamp = run_meta.get("run_ts_ct", format_chicago_timestamp())
    provider = run_meta.get("provider", "unknown")
    data_type = run_meta.get("data_type", "unknown")
    version = run_meta.get("version", "1.0.0")

    # Format picks
    picks_html = ""
    for i, pick in enumerate(picks):
        picks_html += format_pick_html(pick, i)

    # Format leaderboard
    leaderboard_html = format_leaderboard_html(leaderboard)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                 max-width: 800px; margin: 0 auto; padding: 20px; color: #1f2937;">
        <div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); 
                    color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 24px;">Momentum Watchlist</h1>
            <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">
                {timestamp} | Provider: {provider} | Data: {data_type}
            </p>
        </div>
        
        <div style="margin-bottom: 20px;">
            <h2 style="color: #1f2937; border-bottom: 2px solid #22c55e; padding-bottom: 8px;">
                Today's Top Picks ({len(picks)})
            </h2>
            {picks_html if picks else '<p style="color: #6b7280;">No qualifying picks today.</p>'}
        </div>
        
        {leaderboard_html}
        
        {DISCLAIMER}
        
        <p style="font-size: 10px; color: #9ca3af; text-align: center; margin-top: 20px;">
            Momentum Watchlist v{version} | Generated automatically
        </p>
    </body>
    </html>
    """


def format_no_picks_body(
    top_movers: list[dict],
    rejected: list[dict],
    run_meta: dict,
) -> str:
    """Format email body when no picks qualify."""
    timestamp = run_meta.get("run_ts_ct", format_chicago_timestamp())
    provider = run_meta.get("provider", "unknown")

    # Format rejection reasons
    rejection_rows = ""
    for r in rejected[:10]:
        symbol = r.get("symbol", "")
        reason = r.get("rejection_reason", "Unknown")
        rejection_rows += f"<tr><td style='padding: 6px;'>{symbol}</td><td style='padding: 6px;'>{reason}</td></tr>"

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                 max-width: 800px; margin: 0 auto; padding: 20px; color: #1f2937;">
        <div style="background: #f59e0b; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h1 style="margin: 0;">No Picks Today</h1>
            <p style="margin: 8px 0 0 0;">{timestamp} | Provider: {provider}</p>
        </div>
        
        <p>No stocks met all criteria for today's watchlist.</p>
        
        <h3>Top Rejected Candidates:</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="background: #f3f4f6;">
                    <th style="padding: 8px; text-align: left;">Symbol</th>
                    <th style="padding: 8px; text-align: left;">Reason</th>
                </tr>
            </thead>
            <tbody>
                {rejection_rows}
            </tbody>
        </table>
        
        {DISCLAIMER}
    </body>
    </html>
    """


def format_market_closed_body(run_meta: dict) -> str:
    """Format email body for market closed notification."""
    timestamp = run_meta.get("run_ts_ct", format_chicago_timestamp())
    date_str = get_today_date_str()

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                 max-width: 800px; margin: 0 auto; padding: 20px; color: #1f2937;">
        <div style="background: #6b7280; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h1 style="margin: 0;">Market Closed</h1>
            <p style="margin: 8px 0 0 0;">{timestamp}</p>
        </div>
        
        <p>NYSE is closed today ({date_str}). No watchlist generated.</p>
        <p>This could be due to a weekend, holiday, or other market closure.</p>
        
        {DISCLAIMER}
    </body>
    </html>
    """


def send_email(subject: str, html_body: str) -> bool:
    """
    Send email via SendGrid.

    Args:
        subject: Email subject
        html_body: HTML content

    Returns:
        True if sent successfully
    """
    settings = get_settings()
    
    # Log email configuration (redacted)
    api_key_preview = settings.sendgrid_api_key[:10] + "..." if settings.sendgrid_api_key else "MISSING"
    logger.info(f"Email config: from={settings.from_email}, to={settings.to_email}, api_key={api_key_preview}")
    
    if not settings.sendgrid_api_key:
        logger.error("SENDGRID_API_KEY is not set!")
        return False
    if not settings.from_email:
        logger.error("FROM_EMAIL is not set!")
        return False
    if not settings.to_email:
        logger.error("TO_EMAIL is not set!")
        return False

    message = Mail(
        from_email=settings.from_email,
        to_emails=settings.to_email,
        subject=subject,
        html_content=Content(MimeType.html, html_body),
    )

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)

        if response.status_code in (200, 201, 202):
            logger.info(f"Email sent successfully: {subject} (status={response.status_code})")
            return True
        else:
            logger.error(f"Email failed with status {response.status_code}, body={response.body}")
            return False

    except Exception as e:
        logger.error(f"Failed to send email: {type(e).__name__}: {e}")
        return False


def send_watchlist_email(
    picks: list[dict],
    leaderboard: list[dict],
    run_meta: dict,
) -> bool:
    """Send the daily watchlist email."""
    date_str = get_today_date_str()
    subject = f"Momentum Watchlist (8:40 CT): {date_str}"

    body = format_email_body(picks, leaderboard, run_meta)

    return send_email(subject, body)


def send_no_picks_email(
    top_movers: list[dict],
    rejected: list[dict],
    run_meta: dict,
) -> bool:
    """Send email when no picks qualify."""
    date_str = get_today_date_str()
    subject = f"Momentum Watchlist (8:40 CT): {date_str} - No Picks"

    body = format_no_picks_body(top_movers, rejected, run_meta)

    return send_email(subject, body)


def send_market_closed_email(run_meta: dict) -> bool:
    """Send market closed notification."""
    date_str = get_today_date_str()
    subject = f"Momentum Watchlist (8:40 CT): {date_str} - Market Closed"

    body = format_market_closed_body(run_meta)

    return send_email(subject, body)

