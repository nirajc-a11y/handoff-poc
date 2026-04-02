"""Verify a phone number for Plivo trial account outbound calling.

Usage:
    python -m scripts.verify_number +919876543210
"""

import sys
import plivo
from app.config import settings


def main():
    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        print("ERROR: Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env first")
        return

    if len(sys.argv) < 2:
        print("Usage: python -m scripts.verify_number +919876543210")
        return

    phone = sys.argv[1]
    client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)

    print(f"Attempting to verify: {phone}")
    print()

    # Try multiple approaches

    # 1. Try verified caller IDs API
    try:
        response = client.request('POST', ('VerifiedCallerId',), {
            'phone_number': phone,
            'channel': 'call',  # or 'sms'
        })
        print(f"Verification initiated! Check your phone for a call/SMS.")
        print(f"Response: {response}")

        verification_uuid = response.get('verification_uuid', '')
        if verification_uuid:
            otp = input("\nEnter the OTP you received: ").strip()
            verify_response = client.request('POST', ('VerifiedCallerId', 'Verification', verification_uuid), {
                'otp': otp,
            })
            print(f"Verification result: {verify_response}")
        return
    except Exception as e:
        print(f"Method 1 (VerifiedCallerId): {e}")

    # 2. Try sandbox number approach
    try:
        response = client.request('POST', ('Account', settings.plivo_auth_id, 'PhoneNumber', phone, 'Verify'), {})
        print(f"Response: {response}")
        return
    except Exception as e:
        print(f"Method 2 (PhoneNumber Verify): {e}")

    # 3. Try outbound call directly to see error message
    print("\n--- Attempting test call to see trial restrictions ---")
    try:
        response = client.calls.create(
            from_='+911234567890',
            to_=phone,
            answer_url='https://example.com/answer',
            answer_method='POST',
        )
        print(f"Call initiated: {response}")
    except Exception as e:
        error_msg = str(e)
        print(f"Call attempt result: {error_msg}")
        if "not verified" in error_msg.lower() or "sandbox" in error_msg.lower():
            print("\nYour trial account requires number verification.")
            print("Try: Plivo Console -> Phone Numbers -> look for a 'Sandbox' tab")
        elif "from" in error_msg.lower():
            print("\nYou need a Plivo phone number to make outbound calls.")
            print("Go to: Plivo Console -> Phone Numbers -> Buy Number")

    # 4. List any existing verified numbers
    print("\n--- Checking existing verified numbers ---")
    try:
        response = client.request('GET', ('VerifiedCallerId',), {})
        print(f"Verified numbers: {response}")
    except Exception as e:
        print(f"Could not list verified numbers: {e}")


if __name__ == "__main__":
    main()
