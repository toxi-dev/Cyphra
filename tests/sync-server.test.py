#!/usr/bin/env python3
import base64
import concurrent.futures
import http.client
import importlib.util
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

SPEC = importlib.util.spec_from_file_location('cyphra_sync', Path(__file__).resolve().parents[1] / 'server/cyphra_sync.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def envelope(marker=1):
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return {'version': 1, 'nonce': encode(bytes([marker]) * 12), 'ciphertext': encode(bytes([marker]) * 64)}


class SyncServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.invite = secrets.token_urlsafe(32)
        self.token = secrets.token_urlsafe(32)
        self.vault = 'a' * 32
        self.store = module.Store(Path(self.tmp.name), self.invite)
        self.server = module.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, token=None, body=None, extra=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Authorization': f'Bearer {token or self.token}'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        headers.update(extra or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = (response.status, json.loads(response.read()))
        connection.close()
        return result

    def create(self):
        return self.request('POST', '/v1/vaults', self.invite, {'vault': self.vault, 'token': self.token, 'envelope': envelope()})

    def test_real_http_vault_lifecycle_and_opaque_storage(self):
        self.assertEqual(self.create(), (201, {'revision': 1}))
        status, result = self.request('GET', f'/v1/vaults/{self.vault}')
        self.assertEqual(status, 200)
        self.assertEqual(result, {'revision': 1, 'envelope': envelope()})
        self.assertEqual(self.request('PUT', f'/v1/vaults/{self.vault}', body={'revision': 1, 'envelope': envelope(2)}), (200, {'revision': 2}))
        self.assertEqual(self.request('PUT', f'/v1/vaults/{self.vault}', body={'revision': 1, 'envelope': envelope(3)})[0], 409)
        self.assertEqual(self.request('GET', f'/v1/vaults/{self.vault}')[1]['envelope'], envelope(2))
        with self.store.connect() as db:
            row = db.execute('SELECT token_hash, envelope FROM vaults').fetchone()
            self.assertNotEqual(row[0], self.token.encode())
            self.assertNotIn(self.token, row[1])
            self.assertEqual(json.loads(row[1]), envelope(2))

    def test_failed_authentication_and_website_origin_are_rejected(self):
        self.create()
        self.assertEqual(self.request('GET', f'/v1/vaults/{self.vault}', secrets.token_urlsafe(32))[0], 401)
        self.assertEqual(self.request('GET', '/v1/vaults/' + 'b' * 32)[0], 401)
        self.assertEqual(self.request('GET', f'/v1/vaults/{self.vault}', extra={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', f'/v1/vaults/{self.vault}', extra={'Referer': 'https://evil.example/'})[0], 403)
        self.assertEqual(self.request('GET', f'/v1/vaults/{self.vault}?leak=1')[0], 404)
        self.assertEqual(self.request('OPTIONS', f'/v1/vaults/{self.vault}')[0], 405)

    def test_parallel_writers_cannot_overwrite_the_same_revision(self):
        self.create()
        def update(marker):
            return self.request('PUT', f'/v1/vaults/{self.vault}', body={'revision': 1, 'envelope': envelope(marker)})[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(update, [2, 3]))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.request('GET', f'/v1/vaults/{self.vault}')[1]['revision'], 2)

    def test_invalid_plaintext_payload_and_unbounded_bodies_rejected(self):
        self.assertEqual(self.request('POST', '/v1/vaults', self.invite, {'vault': self.vault, 'token': self.token, 'envelope': {'bookmarks': ['https://private.example']}})[0], 400)
        self.create()
        self.assertEqual(self.request('PUT', f'/v1/vaults/{self.vault}', body={'revision': True, 'envelope': envelope()})[0], 400)
        with self.assertRaises(ValueError):
            module.Server(('0.0.0.0', 8766), self.store)
        self.assertEqual(self.request('PUT', f'/v1/vaults/{self.vault}', body={'revision': 1, 'envelope': envelope()}, extra={'Content-Length': str(module.MAX_BODY + 1)})[0], 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
