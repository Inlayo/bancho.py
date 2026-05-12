from __future__ import annotations

import imaplib
import smtplib
import traceback
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from discord_webhook import DiscordEmbed
from discord_webhook import DiscordWebhook
from objects import glob
from objects import logUtils as log

sender_email = glob.config.SenderEmail
sender_password = glob.config.SenderEmailPassword


def exceptionE(msg=""):
    e = traceback.format_exc()
    log.error(f"{msg} \n{e}")
    return e


def mailSend(nick: str, to_email: str, subject: str, body: str, type=" "):
    sc = 200
    msg = MIMEMultipart()
    msg["From"] = f"Inlayo <{sender_email}>"
    if nick and not nick.isascii():
        nick = str(Header(nick, "utf-8").encode())
    msg["To"] = f"{nick} <{to_email}>" if nick else to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        smtp = smtplib.SMTP_SSL(**glob.config.SMTP_serverInfo)
        smtp.login(sender_email, sender_password)
        smtp.sendmail(sender_email, to_email, msg.as_string())
        smtp.quit()
        log.info(f"{type} email sent successfully")
    except Exception as e:
        # SMTPDataError(code, resp), smtplib.SMTPDataError
        exceptionE(f"{type} email send failed : {e}")
        sc = e

    # Copy to sent mail folder
    try:
        if sc == 200:
            imap = imaplib.IMAP4_SSL(**glob.config.IMAP_serverInfo)
            imap.login(sender_email, sender_password)
            imap.append("Sent", None, None, msg.as_bytes())
            log.info("Sent mail folder copied successfully!")
        else:
            log.warning("Sent mail folder copy skipped due to email send failure")
    except Exception as e:
        exceptionE(f"Sent mail folder copy failed : {e}")
        sc = e

    # Send Discord webhook
    try:
        if sc != 200:
            raise sc
        msg = msg.as_string()
        if len(msg) > 4096:
            msg = msg[:4096]  # limit description length
        webhook = DiscordWebhook(url=glob.config.DISCORD_EMAIL_LOG_WEBHOOK)
        embed = DiscordEmbed(description=msg, color=242424)
        embed.set_author(
            name=f"InlayoBot Sent {type}email",
            url=f"https://osu.{glob.config.domain}/u/1",
            icon_url=f"https://a.{glob.config.domain}/1",
        )
        embed.set_footer(text="via Inlayo!")
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        exceptionE(f"Discord webhook send failed! | {e}")
    return sc
