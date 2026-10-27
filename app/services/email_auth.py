from __future__ import annotations

import asyncio
import hashlib
import secrets
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import quote

from redis import asyncio as aioredis

from app import settings
from app.repositories.users import UsersRepository

TOKEN_EXPIRY_SECONDS = 60 * 60


async def send_restriction_notice(email: str, username: str) -> None:
    await _send_email(
        email,
        "Account restriction notice",
        (
            f"Hello {username},\n\n"
            "Your account has been restricted on "
            f"{settings.DOMAIN}.\n\n"
            "If you believe this restriction was made in error, please join our "
            f"Discord server at {settings.DISCORD_INVITE} and contact the staff "
            "team to appeal.\n\n"
            "This is an automated message. Please do not reply to this email."
        ),
    )


async def _send_email(recipient: str, subject: str, body: str) -> None:
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP is not configured.")

    message = EmailMessage()
    message["From"] = formataddr(
        (settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL),
    )
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    def send_sync() -> None:
        smtp_class = smtplib.SMTP_SSL if settings.SMTP_PORT == 465 else smtplib.SMTP
        with smtp_class(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=15,
        ) as smtp:
            if settings.SMTP_TLS and settings.SMTP_PORT != 465:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)

    try:
        await asyncio.to_thread(send_sync)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("Email delivery failed.") from exc


def _token_key(kind: str, token_hash: str) -> str:
    return f"bancho:web_email:{kind}:{token_hash}"


def _pending_key(user_id: int) -> str:
    return f"bancho:web_email:pending:{user_id}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class EmailAuthService:
    users: UsersRepository
    redis: aioredis.Redis
    password_cache: dict[bytes, bytes]

    async def send_registration_verification(self, email: str) -> str:
        token = await self._create_token("signup", email)
        link = f"{settings.WEB_BASE_URL}/register?token={quote(token)}"
        await self._send(
            email,
            "Verify your email address",
            f"Open this link to verify your email, or enter this token on the registration page:\n\n{token}\n\n{link}\n\nThis token expires in one hour.",
        )
        return hashlib.sha256(token.encode()).hexdigest()[:12]

    async def confirm_registration_email(self, token: str) -> str | None:
        email = await self._consume_token("signup", token)
        if email is None:
            return None
        return await self._create_token("signup-proof", email)

    async def consume_registration_proof(self, token: str, email: str) -> bool:
        verified_email = await self._get_token("signup-proof", token)
        return verified_email == email

    async def delete_registration_proof(self, token: str) -> None:
        await self._delete_token("signup-proof", token)

    async def send_verification(self, email: str) -> None:
        user = await self.users.fetch_one(email=email)
        if user is None:
            return
        token = await self._create_token("verify", str(user.id))
        await self.redis.set(_pending_key(user.id), "1", ex=TOKEN_EXPIRY_SECONDS)
        link = f"{settings.WEB_BASE_URL}/verify-email?token={quote(token)}&email={quote(email)}"
        await self._send(
            email,
            "Verify your email address",
            f"Open this link to verify your account:\n\n{link}\n\nThis link expires in one hour.",
        )

    async def verify_email(self, token: str) -> bool:
        user_id = await self._consume_token("verify", token)
        if user_id is None:
            return False
        user = await self.users.fetch_one(id=int(user_id))
        if user is None:
            return False
        await self.redis.delete(_pending_key(user.id))
        return True

    async def is_email_pending(self, user_id: int) -> bool:
        return await self.redis.exists(_pending_key(user_id)) == 1

    async def send_password_reset(self, email: str) -> None:
        user = await self.users.fetch_one(email=email)
        if user is None:
            return
        token = await self._create_token("reset", str(user.id))
        link = f"{settings.WEB_BASE_URL}/forgot-password?token={quote(token)}"
        await self._send(
            email,
            "Reset your password",
            f"Open this link to choose a new password:\n\n{link}\n\nThis link expires in one hour.",
        )

    async def reset_password(self, token: str, password: str) -> bool:
        token = token.strip()
        user_id = await self._get_token("reset", token)
        if user_id is None:
            return False
        user = await self.users.fetch_one(id=int(user_id))
        if user is None:
            return False

        import bcrypt

        password_md5 = hashlib.md5(password.encode()).hexdigest().encode()
        password_bcrypt = bcrypt.hashpw(password_md5, bcrypt.gensalt())
        self.password_cache[password_bcrypt] = password_md5
        await self.users.partial_update(id=user.id, pw_bcrypt=password_bcrypt)
        await self._delete_token("reset", token)
        return True

    async def _create_token(self, kind: str, value: str) -> str:
        token = secrets.token_urlsafe(32)
        await self.redis.set(
            _token_key(kind, _hash_token(token)),
            value,
            ex=TOKEN_EXPIRY_SECONDS,
        )
        return token

    async def _consume_token(self, kind: str, token: str) -> str | None:
        value = await self._get_token(kind, token)
        if value is None:
            return None
        await self._delete_token(kind, token)
        return value

    async def _get_token(self, kind: str, token: str) -> str | None:
        token = token.strip()
        key = _token_key(kind, _hash_token(token))
        value = await self.redis.get(key)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def _delete_token(self, kind: str, token: str) -> None:
        token = token.strip()
        await self.redis.delete(_token_key(kind, _hash_token(token)))

    async def _send(self, recipient: str, subject: str, body: str) -> None:
        await _send_email(recipient, subject, body)
