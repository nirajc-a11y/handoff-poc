"""Update Plivo application webhook URLs to match BASE_WEBHOOK_URL.

Usage:
    python -m scripts.update_webhooks
    python -m scripts.update_webhooks --url https://my-ngrok-url.ngrok-free.app
"""

import argparse
import plivo

from app.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="Override BASE_WEBHOOK_URL")
    args = parser.parse_args()

    base = (args.url or settings.base_webhook_url).rstrip("/")

    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        print("SKIP: PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN not set")
        return

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
                answer_url=f"{base}/api/v1/plivo/answer",
                answer_method="POST",
                fallback_answer_url=f"{base}/api/v1/plivo/fallback",
                fallback_method="POST",
                hangup_url=f"{base}/api/v1/plivo/call-status",
                hangup_method="POST",
            )
            print(f"Plivo app '{app_id}' webhooks -> {base}")
            return

    print("SKIP: No Plivo app named 'Handoff_POC' found")


if __name__ == "__main__":
    main()
