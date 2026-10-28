"""Offline provenance regressions. No real HTTP requests."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import urllib.error

from scripts.collect_rules_evidence import add_collection, collect_source, migrate_manifest, save_bytes


class Response:
    status = 200
    url = 'https://example.test/rules'
    headers = {'Content-Type': 'text/html'}

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


class RulesEvidenceTests(unittest.TestCase):
    def setup_legacy(self, root):
        path = root / 'data/raw/rules/legacy.html'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'old reviewed rules')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {'schema_version': 1, 'sources': [{
            'source_id': 'rules', 'path': 'data/raw/rules/legacy.html',
            'sha256': digest, 'content_status': 'verified', 'bytes': path.stat().st_size}],
            'access_failures': [{'status': 404}]}

    def test_migration_pins_hash_and_keeps_legacy_bytes_and_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = migrate_manifest(root, self.setup_legacy(root))
            source = manifest['sources'][0]
            self.assertEqual((root / source['path']).read_bytes(), b'old reviewed rules')
            self.assertEqual((root / source['legacy_path']).read_bytes(), b'old reviewed rules')
            review = manifest['semantic_reviews'][0]
            self.assertEqual((review['source_id'], review['sha256']), ('rules', source['sha256']))
            self.assertEqual(review['content_status'], 'verified')
            self.assertEqual(manifest['access_failures'], [{'status': 404}])
            self.assertIs(migrate_manifest(root, manifest), manifest)

    def test_changed_response_and_200_placeholder_never_inherit_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = migrate_manifest(root, self.setup_legacy(root))
            pinned = manifest['sources'][0].copy()
            for body in (b'new rules', b'<html>Tencent placeholder</html>', b'old reviewed rules'):
                record = collect_source(root, 'rules', Response.url,
                                        opener=lambda *a, body=body, **kw: Response(body))
                add_collection(manifest, [record])
                self.assertEqual(record['semantic_status'], 'unreviewed')
                self.assertNotIn('content_status', record)
            self.assertEqual(manifest['sources'][0], pinned)
            self.assertEqual((root / pinned['path']).read_bytes(), b'old reviewed rules')
            self.assertEqual(len(manifest['semantic_reviews']), 1)

    def test_http_and_transport_failure_unreviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            errors = [urllib.error.HTTPError(Response.url, 403, 'Forbidden', {}, io.BytesIO(b'denied')),
                      TimeoutError('timeout')]
            for error in errors:
                def fail(*args, **kwargs):
                    raise error
                record = collect_source(root, 'rules', Response.url, opener=fail)
                self.assertEqual(record['semantic_status'], 'unreviewed')
                self.assertNotEqual(record['status'], 200)
                self.assertTrue((root / record['path']).exists())
                self.assertIn('attempted_at_utc', record)
                if isinstance(error, TimeoutError):
                    self.assertNotIn('retrieved_at_utc', record)

    def test_corrupt_existing_content_addressed_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = save_bytes(root, b'original', '.html')
            (root / path).write_bytes(b'corruption')
            with self.assertRaisesRegex(ValueError, 'cache mismatch'):
                save_bytes(root, b'original', '.html')

    def test_changed_legacy_cache_fails_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.setup_legacy(root)
            (root / manifest['sources'][0]['path']).write_bytes(b'changed cache')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                migrate_manifest(root, manifest)


if __name__ == '__main__':
    unittest.main()
