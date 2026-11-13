"""bancho.py's v2 apis for account management"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from fastapi.requests import Request

from app import settings
from app.api import dependencies as api_dependencies
from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.common.responses import Success
from app.api.v2.models.accounts import EmailRequest
from app.api.v2.models.accounts import EmailVerificationResponse
from app.api.v2.models.accounts import PasswordResetRequest
from app.api.v2.models.accounts import RegistrationRequest
from app.api.v2.models.accounts import TokenRequest
from app.api.v2.models.players import Player
from app.services.accounts import AccountRegistrationService
from app.services.accounts import validate_password
from app.services.captcha import CaptchaService
from app.services.email_auth import EmailAuthService

router = APIRouter()


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def register_account(
    request: Request,
    args: RegistrationRequest,
    accounts_service: Annotated[
        AccountRegistrationService,
        Depends(api_dependencies.get_account_registration_service),
    ],
    captcha_service: Annotated[
        CaptchaService,
        Depends(api_dependencies.get_captcha_service),
    ],
    email_auth_service: Annotated[
        EmailAuthService,
        Depends(api_dependencies.get_email_auth_service),
    ],
) -> Success[Player] | Failure:
    if not await captcha_service.verify(args.captcha_token):
        return responses.failure(
            message="Captcha verification failed.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not await email_auth_service.consume_registration_proof(
        args.email_verification_token,
        args.email,
    ):
        return responses.failure(
            message="Email verification is required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    errors = await accounts_service.validate_registration(
        username=args.username,
        email=args.email,
        password=args.password,
    )
    if errors:
        message = " ".join(
            error for field_errors in errors.values() for error in field_errors
        )
        return responses.failure(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    registered_account = await accounts_service.create_account(
        username=args.username,
        email=args.email,
        password=args.password,
        request_headers=request.headers,
    )
    await email_auth_service.delete_registration_proof(
        args.email_verification_token,
    )

    response = Player.model_validate(registered_account.player)
    return responses.success(response, status_code=status.HTTP_201_CREATED)


@router.post("/account/email-verification")
async def send_email_verification(
    args: EmailRequest,
    email_auth_service: Annotated[
        EmailAuthService,
        Depends(api_dependencies.get_email_auth_service),
    ],
) -> Success[None] | Failure:
    try:
        await email_auth_service.send_registration_verification(args.email)
    except RuntimeError:
        return responses.failure(
            "Email delivery is not configured.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return responses.success(None)


@router.post("/account/email-verification/confirm")
async def confirm_email_verification(
    args: TokenRequest,
    email_auth_service: Annotated[
        EmailAuthService,
        Depends(api_dependencies.get_email_auth_service),
    ],
) -> Success[EmailVerificationResponse] | Failure:
    verification_token = await email_auth_service.confirm_registration_email(args.token)
    if verification_token is None:
        return responses.failure(
            "This verification link is invalid or expired.",
            status.HTTP_400_BAD_REQUEST,
        )
    return responses.success(
        EmailVerificationResponse(verification_token=verification_token),
    )


@router.post("/account/password-reset")
async def send_password_reset(
    args: EmailRequest,
    email_auth_service: Annotated[
        EmailAuthService,
        Depends(api_dependencies.get_email_auth_service),
    ],
) -> Success[None] | Failure:
    try:
        await email_auth_service.send_password_reset(args.email)
    except RuntimeError:
        return responses.failure(
            "Email delivery is not configured.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return responses.success(None)


@router.post("/account/password-reset/confirm")
async def confirm_password_reset(
    args: PasswordResetRequest,
    email_auth_service: Annotated[
        EmailAuthService,
        Depends(api_dependencies.get_email_auth_service),
    ],
) -> Success[None] | Failure:
    password_errors = validate_password(args.password, settings.DISALLOWED_PASSWORDS)
    if password_errors:
        return responses.failure(
            " ".join(password_errors),
            status.HTTP_400_BAD_REQUEST,
        )
    if not await email_auth_service.reset_password(args.token, args.password):
        return responses.failure(
            "This reset link is invalid or expired.",
            status.HTTP_400_BAD_REQUEST,
        )
    return responses.success(None)
