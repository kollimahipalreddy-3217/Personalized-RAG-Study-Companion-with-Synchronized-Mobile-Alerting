# ============================================================
#  vapid_setup.py — VAPID Cryptographic Key Generator
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
import base64, os, json

def generate_vapid_keys():
    # Generate private key
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

    # Serialize private key to PEM
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )

    # Get public key in uncompressed point format (for browsers)
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode('utf-8')

    # Save private key
    with open('vapid_private.pem', 'wb') as f:
        f.write(pem)

    # Save public key to a JSON config
    config = {'VAPID_PUBLIC_KEY': pub_b64}
    with open('vapid_config.json', 'w') as f:
        json.dump(config, f)

    print(f"[VAPID] Keys generated!")
    print(f"[VAPID] Public Key: {pub_b64}")
    print(f"[VAPID] Private key saved to: vapid_private.pem")
    print(f"[VAPID] Config saved to: vapid_config.json")
    return pub_b64

if __name__ == '__main__':
    if os.path.exists('vapid_private.pem') and os.path.exists('vapid_config.json'):
        print("[VAPID] Keys already exist. Delete vapid_private.pem and vapid_config.json to regenerate.")
        with open('vapid_config.json') as f:
            config = json.load(f)
        print(f"[VAPID] Existing Public Key: {config.get('VAPID_PUBLIC_KEY','')}")
    else:
        generate_vapid_keys()
