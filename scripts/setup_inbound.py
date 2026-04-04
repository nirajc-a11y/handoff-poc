"""Attach the Plivo phone number to the Handoff_POC application for inbound calls.

This configures the PLIVO_NUMBER from .env so that inbound calls hit
the /api/v1/plivo/answer webhook with the correct tenant_id.

Usage:
    python -m scripts.setup_inbound
    python -m scripts.setup_inbound --tenant-id <UUID>

If --tenant-id is not provided, uses the first tenant from the database.
"""

import argparse
import asyncio

import plivo

from app.config import settings


def find_app(client: plivo.RestClient) -> str | None:
    """Find the Handoff_POC Plivo application."""
    try:
        response = client.applications.list(limit=20)
        app_list = response[0] if isinstance(response, tuple) else response
        items = app_list.objects if hasattr(app_list, "objects") else app_list
        for app_obj in items:
            if getattr(app_obj, "app_name", "") == "Handoff_POC":
                return getattr(app_obj, "app_id")
    except Exception as e:
        print(f"Error listing apps: {e}")
    return None


async def get_first_tenant_id() -> str | None:
    """Fetch the first tenant ID from the database."""
    from sqlalchemy import select
    from app.db.engine import async_session_factory
    from app.db.models.tenant import Tenant

    async with async_session_factory() as db:
        result = await db.execute(select(Tenant.id).limit(1))
        row = result.scalar_one_or_none()
        return str(row) if row else None


def main():
    parser = argparse.ArgumentParser(description="Setup Plivo inbound calling")
    parser.add_argument("--tenant-id", default=None, help="Tenant UUID for inbound calls")
    args = parser.parse_args()

    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        print("ERROR: Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env")
        return

    if not settings.plivo_number:
        print("ERROR: Set PLIVO_NUMBER in .env (e.g. +918031140170)")
        return

    base = settings.base_webhook_url.rstrip("/") if settings.base_webhook_url else ""
    if not base:
        print("ERROR: Set BASE_WEBHOOK_URL in .env (ngrok URL)")
        return

    # Resolve tenant ID
    tenant_id = args.tenant_id
    if not tenant_id:
        print("No --tenant-id provided, fetching from database...")
        tenant_id = asyncio.run(get_first_tenant_id())
        if not tenant_id:
            print("ERROR: No tenants in database. Run 'python -m scripts.seed' first.")
            return
        print(f"Using tenant: {tenant_id}")

    client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)

    # 1. Find or create the Handoff_POC application
    app_id = find_app(client)
    if not app_id:
        print("Creating Handoff_POC application...")
        try:
            resp = client.applications.create(
                app_name="Handoff_POC",
                answer_url=f"{base}/api/v1/plivo/answer?tenant_id={tenant_id}",
                answer_method="POST",
                fallback_answer_url=f"{base}/api/v1/plivo/fallback",
                fallback_method="POST",
                hangup_url=f"{base}/api/v1/plivo/call-status?tenant_id={tenant_id}",
                hangup_method="POST",
            )
            app_id = resp["app_id"]
            print(f"Created app: {app_id}")
        except Exception as e:
            print(f"ERROR: Failed to create app: {e}")
            return
    else:
        # Update the existing app's webhook URLs with tenant_id
        print(f"Updating app {app_id} webhook URLs...")
        try:
            client.applications.update(
                app_id,
                answer_url=f"{base}/api/v1/plivo/answer?tenant_id={tenant_id}",
                answer_method="POST",
                fallback_answer_url=f"{base}/api/v1/plivo/fallback",
                fallback_method="POST",
                hangup_url=f"{base}/api/v1/plivo/call-status?tenant_id={tenant_id}",
                hangup_method="POST",
            )
            print(f"Updated webhooks -> {base} (tenant={tenant_id})")
        except Exception as e:
            print(f"ERROR: Failed to update app: {e}")
            return

    # 2. Attach the phone number to the application
    number = settings.plivo_number.lstrip("+")
    print(f"\nAttaching number {settings.plivo_number} to app {app_id}...")

    try:
        # Find the number in the account (use number_startswith to search)
        response = client.numbers.list(number_startswith=number, limit=5)
        num_list = response[0] if isinstance(response, tuple) else response
        items = num_list.objects if hasattr(num_list, "objects") else num_list

        found = False
        for num_obj in items:
            num_id = getattr(num_obj, "number", "")
            current_app = getattr(num_obj, "application", "")
            print(f"  Found number: {num_id} (current app: {current_app or 'none'})")

            # Update number to use our app
            client.numbers.update(num_id, app_id=app_id)
            print(f"  Attached to app {app_id}")
            found = True
            break

        if not found:
            print(f"  Number {settings.plivo_number} not found in your Plivo account.")
            print(f"  Buy it from Plivo console and re-run this script.")
            return

    except Exception as e:
        print(f"ERROR attaching number: {e}")
        return

    # 3. Summary
    print("\n" + "=" * 60)
    print("INBOUND CALLING SETUP COMPLETE")
    print("=" * 60)
    print(f"Phone Number : {settings.plivo_number}")
    print(f"Application  : {app_id}")
    print(f"Tenant       : {tenant_id}")
    print(f"Webhook Base : {base}")
    print(f"Answer URL   : {base}/api/v1/plivo/answer?tenant_id={tenant_id}")
    print(f"Hangup URL   : {base}/api/v1/plivo/call-status?tenant_id={tenant_id}")
    print()
    print("Inbound calls to this number will now:")
    print("  1. Hit /answer with the correct tenant_id")
    print("  2. Play IVR menu (Polly.Aditi voice)")
    print("  3. Route to AI agent or human queue based on DTMF")
    print("=" * 60)


if __name__ == "__main__":
    main()
