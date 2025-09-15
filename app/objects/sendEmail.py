from __future__ import annotations

import asyncio
import imaplib
import smtplib
import traceback
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import app.settings
from app.discord import Embed
from app.discord import Webhook
from app.objects import logUtils as log

sender_email = app.settings.SenderEmail
sender_password = app.settings.SenderEmailPassword


def exceptionE(msg: str = "") -> str:
    e = traceback.format_exc()
    log.error(f"{msg} \n{e}")
    return e


def mailSend(
    nick: str,
    to_email: str,
    subject: str,
    body: str,
    type: str = " ",
    html: bool = False,
) -> int | Exception:
    sc: int | Exception = 200
    msg = MIMEMultipart()
    msg["From"] = f"InlayoBot <{sender_email}>"
    if nick and not nick.isascii():
        nick = str(Header(nick, "utf-8").encode())
    msg["To"] = f"{nick} <{to_email}>" if nick else to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain"))

    try:
        smtp = smtplib.SMTP_SSL(**app.settings.SMTP_serverInfo)
        smtp.login(sender_email, sender_password)
        smtp.sendmail(sender_email, to_email, msg.as_string())
        smtp.quit()
        log.info(f"{type} 이메일 전송 성공")
    except Exception as e:
        # SMTPDataError(code, resp), smtplib.SMTPDataError
        exceptionE(f"{type} 이메일 전송 실패 : {e}")
        sc = e

    # 보낸메일함에 복사
    try:
        if sc == 200:
            imap = imaplib.IMAP4_SSL(**app.settings.IMAP_serverInfo)
            imap.login(sender_email, sender_password)
            imap.append("Sent", "", "", msg.as_bytes())
            log.info("보낸메일함 복사 성공!")
        else:
            log.warning("메일 전송 실패함에 따라 보낸메일함 복사는 하지 않음")
    except Exception as e:
        exceptionE(f"보낸메일함 복사 실패 : {e}")
        sc = e

    # 디코 웹훅 전송
    try:
        if sc != 200:
            raise sc  # type: ignore
        if type == "AutoBan" or type == "Ban":
            origin = msg.as_string()
            msg = origin[: origin.find("Content-Type: text/html;")]  # type: ignore
            msg += origin[msg.find('<a id="Reason for sending mail"') : origin.find("</a>", origin.find('<a id="Reason for sending mail"')) + 4]  # type: ignore
        else:
            msg = msg.as_string()  # type: ignore
        if len(msg) > 4096:
            msg = msg[:4096]  # type: ignore #description 길이제한
        embed = Embed(description=msg, color=242424)
        embed.set_author(
            name=f"BanchoBot Sent {type}email",
            url=f"https://{app.settings.DOMAIN}/u/1",
            icon_url=f"https://a.{app.settings.DOMAIN}/1",
        )
        embed.set_footer(text="via bancho.py!")
        embed.set_timestamp()
        webhook = Webhook(url=app.settings.DISCORD_EMAIL_LOG_WEBHOOK, embeds=[embed])
        asyncio.run_coroutine_threadsafe(webhook.post(), app.state.loop)
    except Exception as e:
        exceptionE(f"디코 웹훅 전송 실패! | {e}")
    return sc
