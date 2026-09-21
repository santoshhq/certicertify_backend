import asyncio
import os
import smtplib
from email.message import EmailMessage
from html import escape

from dotenv import load_dotenv


load_dotenv()

LOGO_URL = "https://certicertify.s3.ap-south-1.amazonaws.com/certicertify_logo.png"


def _smtp_settings() -> tuple[str, int, str, str, str, str]:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "465"))

    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    from_email = os.getenv("SMTP_FROM_EMAIL")
    from_name = os.getenv("SMTP_FROM_NAME", "CertiCertify")

    if not host or not username or not password or not from_email:
        raise RuntimeError(
            "SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL "
            "must be configured"
        )

    return host, port, username, from_email, from_name, password
    
def _send_html_email_sync(
        recipient: str,
        subject: str,
        plain_text: str,
        html_content: str,
) -> None:
        host, port, username, sender, from_name, password = _smtp_settings()
    
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = recipient
        message.set_content(plain_text)
        message.add_alternative(html_content, subtype="html")
    
        # Port 465 uses implicit TLS; other ports (e.g. 587) use STARTTLS.
        if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                        smtp.login(username, password)
                        smtp.send_message(message)
        else:
                with smtplib.SMTP(host, port, timeout=30) as smtp:
                        smtp.ehlo()
                        smtp.starttls()
                        smtp.ehlo()
                        smtp.login(username, password)
                        smtp.send_message(message)
    
def _email_layout(title: str, preheader: str, body_html: str) -> str:
        """Wrap email body HTML in the shared CertiCertify branded shell."""
        safe_title = escape(title)
        safe_preheader = escape(preheader)
        return f"""<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="x-apple-disable-message-reformatting" />
    <title>{safe_title}</title>
</head>
<body style="margin:0;padding:0;background:#f3faf5;color:#173b2a;font-family:Arial,Helvetica,sans-serif;-webkit-font-smoothing:antialiased;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#f3faf5;font-size:1px;line-height:1px;">{safe_preheader}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3faf5;">
        <tr>
            <td align="center" style="padding:40px 16px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;">
                    <!-- Card -->
                    <tr>
                        <td style="background:#ffffff;border:1px solid #d7eadc;border-radius:14px;overflow:hidden;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                                <!-- Accent bar -->
                                <tr>
                                    <td style="height:5px;background:#287a48;font-size:0;line-height:0;">&nbsp;</td>
                                </tr>
                                <!-- Header with logo -->
                                <tr>
                                    <td align="center" style="padding:32px 28px 24px;background:#dff3e5;border-bottom:1px solid #c5e5ce;">
                                        <img src="{LOGO_URL}" alt="CertiCertify" width="150" height="150" style="display:block;width:150px;max-width:150px;height:auto;border:0;outline:none;text-decoration:none;" />
                                    </td>
                                </tr>
                                <!-- Body -->
                                <tr>
                                    <td style="padding:32px 28px 8px;">
                                        <h1 style="margin:0 0 12px;font-size:24px;line-height:1.3;font-weight:bold;color:#173b2a;text-align:center;">{safe_title}</h1>
                                        {body_html}
                                    </td>
                                </tr>
                                <!-- Footer -->
                                <tr>
                                    <td style="padding:20px 28px 24px;">
                                        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                                            <tr>
                                                <td style="border-top:1px solid #d7eadc;font-size:0;line-height:0;">&nbsp;</td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding-top:16px;font-size:12px;line-height:1.6;color:#718579;">
                                                    This is an automated message from CertiCertify. Please do not reply to this email.
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- Below-card note -->
                    <tr>
                        <td align="center" style="padding:20px 12px 0;font-size:12px;line-height:1.6;color:#718579;">
                            &copy; CertiCertify &middot; Verify the authentications
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


def _email_template(title: str, intro: str, otp: str, expiry: str) -> str:
        """Build the OTP email (account verification / password reset)."""
        safe_intro = escape(intro)
        safe_otp = escape(otp)
        safe_expiry = escape(expiry)
        body = f"""<p style="margin:0 0 24px;font-size:16px;line-height:1.6;color:#173b2a;text-align:center;">{safe_intro}</p>
                                        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 24px;">
                                            <tr>
                                                <td align="center" style="padding:24px 18px;background:#effaf1;border:1px solid #c5e5ce;border-radius:10px;">
                                                    <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#4c765c;font-weight:bold;">Your 6-digit code</div>
                                                    <div style="margin-top:10px;font-size:36px;line-height:1.2;font-weight:bold;letter-spacing:10px;color:#287a48;font-family:'Courier New',Courier,monospace;">{safe_otp}</div>
                                                    <div style="margin-top:10px;font-size:13px;color:#557061;">Expires in <strong style="color:#287a48;">{safe_expiry}</strong></div>
                                                </td>
                                            </tr>
                                        </table>
                                        <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#557061;text-align:center;">For your security, never share this code with anyone. If you did not request this email, you can safely ignore it.</p>"""
        return _email_layout(title, f"Your CertiCertify code is {otp}. It expires in {expiry}.", body)


async def institution_account_verify(recipient: str, otp: str) -> None:
        """Send the six-digit institution account verification OTP."""
        html_content = _email_template(
                "Verify your institution account",
                "Use the verification code below to complete your institution registration.",
                otp,
                "5 minutes",
        )
        await asyncio.to_thread(
                _send_html_email_sync,
                recipient,
                "Verify your CertiCertify institution account",
                f"Your institution verification OTP is {otp}. It expires in 5 minutes.",
                html_content,
        )

async def superadmin_account_verify(recipient: str, otp: str) -> None:
        """Send the six-digit superadmin account verification OTP."""
        html_content = _email_template(
                "Verify your superadmin account",
                "Use the verification code below to complete your superadmin registration.",
                otp,
                "5 minutes",
        )
        await asyncio.to_thread(
                _send_html_email_sync,
                recipient,
                "Verify your CertiCertify superadmin account",
                f"Your superadmin verification OTP is {otp}. It expires in 5 minutes.",
                html_content,
        )
    
async def institution_password_reset(recipient: str, otp: str) -> None:
        """Send the six-digit institution password reset OTP."""
        html_content = _email_template(
                "Reset your institution password",
                "Use the code below to confirm your institution password reset request.",
                otp,
                "5 minutes",
        )
        await asyncio.to_thread(
                _send_html_email_sync,
                recipient,
                "Reset your CertiCertify institution password",
                f"Your institution password reset OTP is {otp}. It expires in 5 minutes.",
                html_content,
        )

async def superadmin_password_reset(recipient: str, otp: str) -> None:
        """Send the six-digit superadmin password reset OTP."""
        html_content = _email_template(
                "Reset your superadmin password",
                "Use the code below to confirm your superadmin password reset request.",
                otp,
                "5 minutes",
        )
        await asyncio.to_thread(
                _send_html_email_sync,
                recipient,
                "Reset your CertiCertify superadmin password",
                f"Your superadmin password reset OTP is {otp}. It expires in 5 minutes.",
                html_content,
        )

async def admin_account_created(
                recipient: str,
                admin_name: str,
                admin_login_id: str,
                password: str,
) -> None:
                """Send the newly created admin their login credentials."""
                safe_name = escape(admin_name)
                safe_login_id = escape(admin_login_id)
                safe_password = escape(password)
                body = f"""<p style="margin:0 0 24px;font-size:16px;line-height:1.6;color:#173b2a;text-align:center;">Hello {safe_name}, your CertiCertify admin account has been created. Use the credentials below to sign in.</p>
                                        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 24px;">
                                            <tr>
                                                <td style="padding:8px 18px;background:#effaf1;border:1px solid #c5e5ce;border-radius:10px;">
                                                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                                                        <tr>
                                                            <td style="padding:12px 0;border-bottom:1px solid #c5e5ce;font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4c765c;font-weight:bold;">Admin login ID</td>
                                                            <td align="right" style="padding:12px 0;border-bottom:1px solid #c5e5ce;font-size:16px;font-weight:bold;color:#173b2a;font-family:'Courier New',Courier,monospace;">{safe_login_id}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding:12px 0;font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4c765c;font-weight:bold;">Password</td>
                                                            <td align="right" style="padding:12px 0;font-size:16px;font-weight:bold;color:#287a48;font-family:'Courier New',Courier,monospace;">{safe_password}</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                        <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#557061;text-align:center;">Please keep these credentials private and change your password after your first sign-in.</p>"""
                html_content = _email_layout(
                                "Your admin account is ready",
                                f"Hello {admin_name}, your CertiCertify admin credentials are inside.",
                                body,
                )
                await asyncio.to_thread(
                                _send_html_email_sync,
                                recipient,
                                "Your CertiCertify admin account credentials",
                                f"Hello {admin_name}, your admin login ID is {admin_login_id} and your password is {password}.",
                                html_content,
                )
    
async def send_otp_email(recipient: str, otp: str) -> None:
        """Backward-compatible alias for institution account verification."""
        await institution_account_verify(recipient, otp)


