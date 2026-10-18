"""Bound the optional unsigned envelope around signed OneCRL metadata."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refresh_security_data', ROOT / 'scripts/refresh-security-data.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class CollectionMetadataTests(unittest.TestCase):
    def test_legacy_data_only_envelope_preserves_signed_metadata(self):
        data = {'signature': {'signature': 'untouched'}, 'schema': {'type': 'object'}}
        self.assertIs(refresh.collection_metadata({'data': data}), data)

    def test_empty_permissions_envelope_preserves_signed_metadata(self):
        data = {'signature': {'signature': 'untouched'}, 'last_modified': 123}
        self.assertIs(refresh.collection_metadata({'data': data, 'permissions': {}}), data)

    def test_nonempty_or_malformed_permissions_are_rejected(self):
        for permissions in ({'read': ['system.Everyone']}, [], None, '', False):
            with self.subTest(permissions=permissions), self.assertRaisesRegex(ValueError, 'collection metadata'):
                refresh.collection_metadata({'data': {}, 'permissions': permissions})

    def test_additional_envelope_fields_are_rejected(self):
        for value in ({'data': {}, 'extra': {}}, {'data': {}, 'permissions': {}, 'extra': {}}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'collection metadata'):
                refresh.collection_metadata(value)

    def test_missing_or_malformed_collection_data_is_rejected(self):
        for value in ({}, {'permissions': {}}, {'data': None}, {'data': []}, [], None, 'metadata'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'collection metadata'):
                refresh.collection_metadata(value)


if __name__ == '__main__':
    unittest.main()
