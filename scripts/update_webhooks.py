"""Update Plivo application webhook URLs to match BASE_WEBHOOK_URL.

Usage:
    python -m scripts.update_webhooks
    python -m scripts.update_webhooks --url https://my-ngrok-url.ngrok-free.app
    python -m scripts.update_webhooks --tenant-id <UUID>
"""

import argparse
import asyncio

import plivo

from app.config import settings


async def get_first_tenant_id() -> str | None:
    from sqlalchemy import select
    from app.db.engine import async_session_factory
    from app.db.models.tenant import Tenant

    async with async_session_factory() as db:
        result = await db.execute(select(Tenant.id).limit(1))
        row = result.scalar_one_or_none()
        return str(row) if row else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="Override BASE_WEBHOOK_URL")
    parser.add_argument("--tenant-id", default=None, help="Tenant UUID for inbound webhooks")
    args = parser.parse_args()

    base = (args.url or settings.base_webhook_url).rstrip("/")

    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        print("SKIP: PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN not set")
        return

    # Resolve tenant ID for webhook URLs
    tenant_id = args.tenant_id
    if not tenant_id:
        tenant_id = asyncio.run(get_first_tenant_id())
    tenant_param = f"?tenant_id={tenant_id}" if tenant_id else ""

    client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)

    # Find the Handoff_POC application
    try:
        response = client.applications.list(limit=20)
        app_list = response[0] if isinstance(response, tuple) else response
        items = app_list.objects if hasattr(app_list, "objects") else app_list
    except Exception as e:
        print(f"SKIP: Could not list Plivo apps: {e}")
        return

    for app_obj in items:
        if getattr(app_obj, "app_name", "") == "Handoff_POC":
            app_id = getattr(app_obj, "app_id")
            client.applications.update(
                app_id,
                answer_url=f"{base}/api/v1/plivo/answer{tenant_param}",
                answer_method="POST",
                fallback_answer_url=f"{base}/api/v1/plivo/fallback",
                fallback_method="POST",
                hangup_url=f"{base}/api/v1/plivo/call-status{tenant_param}",
                hangup_method="POST",
            )
            print(f"Plivo app '{app_id}' webhooks -> {base}")
            if tenant_id:
                print(f"  tenant_id={tenant_id}")
            return

    print("SKIP: No Plivo app named 'Handoff_POC' found")


if __name__ == "__main__":
    main()
