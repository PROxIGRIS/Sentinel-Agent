import json
import base64
from nacl.signing import VerifyKey
import time

LICENSE_VERIFY_KEY_B64 = 'oQYy7eR/qxZOlKw/v9QNpmrcDWpNKGOx2YM0q++oXaY='
HARDWARE_UUID = 'TEST-UUID'

payload = {
    'license_id': '456',
    'node_id': '123',
    'expires_at': None,
    'issued_at': '2026-08-29T13:43:53.000Z',
    'status': 'active'
}

sign_payload = json.dumps({
    'license_id': payload.get('license_id'),
    'node_id': payload.get('node_id'),
    'hardware_uuid': HARDWARE_UUID,
    'expires_at': payload.get('expires_at'),
    'issued_at': payload.get('issued_at'),
    'status': payload.get('status')
}, separators=(',', ':')).encode('utf-8')

print('PYTHON sign_payload:', sign_payload)
