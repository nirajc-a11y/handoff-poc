"""Configure Twilio number webhooks and verify caller IDs.

Usage:
    python -m scripts.setup_twilio
"""

from twilio.rest import Client
from app.config import settings


def main():
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        print("ERROR: Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env first")
        return

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    base = settings.base_webhook_url.rstrip("/")
    tenant_id = input("Enter your tenant_id (from seed script): ").strip()

    if not tenant_id:
        print("ERROR: tenant_id is required")
        return

    # --- Configure phone number webhooks ---
    print(f"\nConfiguring webhooks for {settings.twilio_number}...")
    try:
        numbers = client.incoming_phone_numbers.list(phone_number=settings.twilio_number)
        if not numbers:
            print(f"  ERROR: Number {settings.twilio_number} not found in your account")
            return

        number = numbers[0]
        number.update(
            voice_url=f"{base}/api/v1/twilio/answer?tenant_id={tenant_id}",
            voice_method="POST",
            voice_fallback_url=f"{base}/api/v1/twilio/fallback",
            voice_fallback_method="POST",
            status_callback=f"{base}/api/v1/twilio/call-status",
            status_callback_method="POST",
        )
        print(f"  Answer URL:  {base}/api/v1/twilio/answer?tenant_id={tenant_id}")
        print(f"  Fallback:    {base}/api/v1/twilio/fallback")
        print(f"  Status CB:   {base}/api/v1/twilio/call-status")
        print("  Webhooks configured!")
    except Exception as e:
        print(f"  ERROR: {e}")

    # --- List verified caller IDs ---
    print("\nVerified Caller IDs:")
    try:
        callerids = client.outgoing_caller_ids.list()
        if callerids:
            for cid in callerids:
                print(f"  - {cid.phone_number} ({cid.friendly_name})")
        else:
            print("  None found.")
    except Exception as e:
        print(f"  ERROR: {e}")

    # --- Ask to verify a number ---
    verify = input("\nWant to verify a phone number for outbound calls? (enter number or skip): ").strip()
    if verify and verify != "skip":
        try:
            validation = client.validation_requests.create(
                friendly_name="Demo Phone",
                phone_number=verify,
            )
            print(f"\n  Twilio is calling {verify} now!")
            print(f"  Validation code: {validation.validation_code}")
            print(f"  Answer the call and enter the code when prompted.")
        except Exception as e:
            print(f"  ERROR: {e}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("TWILIO SETUP COMPLETE")
    print("=" * 60)
    print(f"Number:      {settings.twilio_number}")
    print(f"Webhook URL: {base}/api/v1/twilio/answer?tenant_id={tenant_id}")
    print(f"\nTo test:")
    print(f"  1. Make sure server is running: python -m uvicorn app.main:app --port 8000")
    print(f"  2. Make sure ngrok is running: ngrok http 8000")
    print(f"  3. Call {settings.twilio_number} from your verified phone")
    print(f"  4. You'll hear the IVR menu!")
    print("=" * 60)


if __name__ == "__main__":
    main()
