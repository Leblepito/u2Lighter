#!/usr/bin/env python3
"""
Delivery Notification Service

Watches for completed GitHub Actions runs and notifies customers
with their AR viewer link, USDZ download, QR code, and print files.
"""
from __future__ import annotations

import asyncio
import json
import os
import smtplib
import sys
import time
from dataclasses import asdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Leblepito/u2Lighter")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@u2lighter.com")
BASE_URL = os.getenv("BASE_URL", "https://u2lighter.com")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))  # seconds

# Email template
DELIVERY_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%); border-radius: 16px; padding: 40px; text-align: center; margin-bottom: 24px;">
        <h1 style="color: #ec4899; margin: 0 0 8px; font-size: 28px;">Your Custom Sleeve is Ready! ✨</h1>
        <p style="color: #831843; margin: 0; font-size: 16px;">Order #{order_id}</p>
    </div>

    <div style="background: white; border-radius: 12px; padding: 24px; border: 1px solid #fce7f3;">
        <p style="font-size: 16px; margin-bottom: 16px;">Your custom lighter sleeve has been generated, printed, and rendered. Here's everything you need:</p>

        <div style="display: flex; flex-direction: column; gap: 12px; margin: 24px 0;">
            <a href="{viewer_url}" style="display: inline-block; background: #ec4899; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px;">
                🎮 View in AR / 3D
            </a>
            <a href="{usdz_url}" style="display: inline-block; background: #0ea5e9; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px;" download>
                📱 Download USDZ (iOS AR)
            </a>
            <a href="{stl_url}" style="display: inline-block; background: #22c55e; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px;" download>
                🖨️ Download STL for Printing
            </a>
            <a href="{threemf_url}" style="display: inline-block; background: #8b5cf6; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px;" download>
                📦 Download 3MF (Full Color)
            </a>
        </div>

        <div style="text-align: center; margin: 24px 0;">
            <img src="{qr_url}" alt="QR Code for AR Viewer" style="max-width: 180px; border-radius: 8px; border: 1px solid #fce7f3;">
            <p style="margin: 8px 0 0; font-size: 14px; color: #831843;">Scan with iPhone camera to open in AR</p>
        </div>

        <hr style="border: none; border-top: 1px solid #fce7f3; margin: 24px 0;">

        <h3 style="color: #374150; margin-bottom: 12px;">What's Included</h3>
        <ul style="padding-left: 20px; color: #4b5563;">
            <li><strong>AR Viewer:</strong> Interactive 3D model in browser (works on all devices)</li>
            <li><strong>USDZ File:</strong> Opens instantly in iOS AR Quick Look (iPhone/iPad)</li>
            <li><strong>STL/3MF Files:</strong> Ready for 3D printing (Bambu Studio, PrusaSlicer, etc.)</li>
            <li><strong>QR Code:</strong> Quick access to AR viewer on mobile</li>
        </ul>

        <hr style="border: none; border-top: 1px solid #fce7f3; margin: 24px 0;">

        <p style="color: #6b7280; font-size: 14px;">
            Your design: <strong>{figure_name}</strong><br>
            Plinth color: <strong>{plinth_color}</strong><br>
            Pin config: <strong>{pins}</strong><br>
            Completed: <strong>{completed_at}</strong>
        </p>

        <p style="color: #9ca3af; font-size: 13px; margin-top: 24px;">
            Questions? Reply to this email or visit <a href="{base_url}" style="color: #ec4899;">u2lighter.com</a>
        </p>
    </div>

    <div style="text-align: center; margin-top: 24px; color: #9ca3af; font-size: 12px;">
        u2Lighter — Light your style<br>
        <a href="{base_url}/unsubscribe" style="color: #9ca3af;">Unsubscribe</a>
    </div>
</body>
</html>
"""

FAILURE_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: #fef2f2; border-radius: 16px; padding: 40px; text-align: center; margin-bottom: 24px;">
        <h1 style="color: #dc2626; margin: 0 0 8px; font-size: 28px;">Something went wrong 😔</h1>
        <p style="color: #991b1b; margin: 0; font-size: 16px;">Order #{order_id}</p>
    </div>

    <div style="background: white; border-radius: 12px; padding: 24px; border: 1px solid #fecaca;">
        <p style="font-size: 16px; margin-bottom: 16px;">We're sorry — your custom sleeve couldn't be generated automatically. This can happen with complex designs or temporary service issues.</p>

        <div style="background: #fef2f2; border-radius: 8px; padding: 16px; margin: 16px 0; text-align: left;">
            <strong>Error:</strong> {error_message}
        </div>

        <p style="margin: 24px 0 0;">Our team has been notified and will review your order manually. You'll receive a follow-up email within 24 hours with either:</p>
        <ul style="padding-left: 20px; color: #4b5563;">
            <li>A working AR viewer link and files</li>
            <li>A request for a different reference image</li>
            <li>A refund if we can't fulfill the order</li>
        </ul>

        <p style="margin-top: 24px;">Questions? Reply to this email — we're here to help.</p>
    </div>
</body>
</html>
"""


class EmailSender:
    def __init__(self):
        self.enabled = all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM])

    def send(self, to: str, subject: str, html: str) -> bool:
        if not self.enabled:
            print(f"[EMAIL] Would send to {to}: {subject}")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = EMAIL_FROM
            msg["To"] = to
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"[EMAIL] Failed to send to {to}: {e}")
            return False


async def get_completed_workflow_runs(since: datetime) -> list[dict]:
    """Fetch completed workflow runs from GitHub."""
    if not GITHUB_TOKEN:
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json"
            },
            params={
                "status": "completed",
                "created": f">{since.isoformat()}Z",
                "per_page": 50
            }
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("workflow_runs", [])


async def get_run_artifacts(run_id: int) -> list[dict]:
    """Get artifacts for a workflow run."""
    if not GITHUB_TOKEN:
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/artifacts",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json"
            }
        )
        resp.raise_for_status()
        return resp.json().get("artifacts", [])


async def get_supabase_orders(status: str = "queued") -> list[dict]:
    """Fetch orders from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/orders",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            },
            params={
                "status": f"eq.{status}",
                "select": "*"
            }
        )
        resp.raise_for_status()
        return resp.json()


async def update_supabase_order(order_id: str, updates: dict) -> None:
    """Update order in Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/orders",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            params={"order_id": f"eq.{order_id}"},
            json=updates
        )
        resp.raise_for_status()


def build_asset_urls(base_url: str, figure_id: str) -> dict[str, str]:
    """Build URLs for all delivery assets."""
    return {
        "viewer": f"{base_url}/ar/{figure_id}",
        "usdz": f"{base_url}/ar/{figure_id}.usdz",
        "stl": f"{base_url}/download/{figure_id}.stl",
        "threemf": f"{base_url}/download/{figure_id}.3mf",
        "qr": f"{base_url}/qr/{figure_id}.png"
    }


async def send_delivery_email(order: dict, asset_urls: dict) -> bool:
    """Send successful delivery email."""
    sender = EmailSender()
    html = DELIVERY_EMAIL_TEMPLATE.format(
        order_id=order["order_id"],
        viewer_url=asset_urls["viewer"],
        usdz_url=asset_urls["usdz"],
        stl_url=asset_urls["stl"],
        threemf_url=asset_urls["threemf"],
        qr_url=asset_urls["qr"],
        figure_name=order.get("figure_name", "Custom Sleeve"),
        plinth_color=order.get("plinth_color", "Pembe"),
        pins=order.get("pins", "8,4,2"),
        completed_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        base_url=BASE_URL
    )
    return sender.send(
        order["customer_email"],
        f"🎉 Your custom lighter sleeve is ready! Order #{order['order_id']}",
        html
    )


async def send_failure_email(order: dict, error: str) -> bool:
    """Send failure notification email."""
    sender = EmailSender()
    html = FAILURE_EMAIL_TEMPLATE.format(
        order_id=order["order_id"],
        error_message=error
    )
    return sender.send(
        order["customer_email"],
        f"⚠️ Issue with your custom sleeve order #{order['order_id']}",
        html
    )


async def check_and_notify() -> int:
    """Check for completed orders and send notifications."""
    notified = 0
    sender = EmailSender()

    # Get orders awaiting delivery
    orders = await get_supabase_orders("queued")
    if not orders:
        return 0

    # Get recent completed workflow runs
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    runs = await get_completed_workflow_runs(since)

    for order in orders:
        figure_id = f"custom_{order['order_id']}"

        # Check if there's a completed run for this figure
        matching_run = None
        for run in runs:
            if run.get("name", "").startswith("Custom Order") and figure_id in str(run):
                if run.get("conclusion") == "success":
                    matching_run = run
                    break

        if matching_run:
            # Success! Build asset URLs and send email
            asset_urls = build_asset_urls(BASE_URL, figure_id)
            await send_delivery_email(order, asset_urls)

            await update_supabase_order(order["order_id"], {
                "status": "delivered",
                "completed_at": datetime.utcnow().isoformat(),
                "github_run_id": matching_run["id"]
            })
            notified += 1
            print(f"[NOTIFY] Delivered order {order['order_id']}")

        elif any(run.get("conclusion") == "failure" and figure_id in str(run) for run in runs):
            # Failure - send apology email
            error_msg = "Pipeline failed during generation"
            await send_failure_email(order, error_msg)

            await update_supabase_order(order["order_id"], {
                "status": "failed",
                "error_message": error_msg,
                "completed_at": datetime.utcnow().isoformat()
            })
            notified += 1
            print(f"[NOTIFY] Failed order {order['order_id']} notified")

    return notified


async def main():
    """Main loop for notification service."""
    print(f"[DELIVERY] Starting notification service (interval: {CHECK_INTERVAL}s)")
    print(f"[DELIVERY] Repo: {GITHUB_REPO}")
    print(f"[DELIVERY] Email: {'enabled' if EmailSender().enabled else 'disabled (demo mode)'}")

    while True:
        try:
            notified = await check_and_notify()
            if notified:
                print(f"[DELIVERY] Sent {notified} notifications")
        except Exception as e:
            print(f"[DELIVERY] Error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())