import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
from backend import server
from backend.input_data import CATALOG, validate_inventory, validate_options

def inventory():
    return {'schema_version': 1, 'name': 'API test stock',
            'geometry': {'stud_pitch': 5, 'layer_height': 6, 'units': 'relative'},
            'parts': [{'id': key, 'studs': list(size), 'height_layers': 1,
                       'role': 'detail' if key == '1x1' else 'structure', 'quantity': 20}
                      for key, size in CATALOG.items()]}

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.patches = [patch.object(server, 'TOPOLOGIES', root / 'topologies'), patch.object(server, 'JOBS', root / 'jobs')]
        for change in self.patches:
            change.start()
        self.client = TestClient(server.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for change in reversed(self.patches):
            change.stop()
        self.directory.cleanup()

    def test_upload_and_content_addressed_storage(self):
        buffer = io.BytesIO()
        np.savez_compressed(buffer, density=np.ones((4, 3, 2)), design=np.zeros((4, 3, 2)))
        first = self.client.post('/api/topology', content=buffer.getvalue(), headers={'x-filename': 'cube.npz'})
        self.assertEqual(first.status_code, 200)
        uploaded = first.json()
        self.assertEqual(uploaded['arrays'][0]['shape'], [4, 3, 2])
        second = self.client.post('/api/topology', content=buffer.getvalue())
        self.assertEqual(second.json()['id'], uploaded['id'])
        self.assertEqual(len(list(server.TOPOLOGIES.glob('*.npz'))), 1)

    def test_bad_inputs_do_not_start_jobs_or_leave_uploads(self):
        bad_file = self.client.post('/api/topology', content=b'not an npz')
        self.assertEqual(bad_file.status_code, 422)
        self.assertEqual(list(server.TOPOLOGIES.glob('*')), [])
        malformed = self.client.post('/api/assembly', content=b'[]')
        self.assertEqual(malformed.status_code, 422)
        bad_stock = inventory()
        bad_stock['parts'][0]['role'] = 'structure'
        invalid = self.client.post('/api/assembly', json={'topology_id': 'a' * 64, 'inventory': bad_stock})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(list(server.JOBS.glob('*')), [])

    def test_static_and_api_share_origin_without_exposing_data_directory(self):
        self.assertEqual(self.client.get('/api/health').json()['status'], 'ok')
        self.assertIn('TopoLegOpt', self.client.get('/').text)
        self.assertEqual(self.client.get('/.local/').status_code, 404)
        self.assertEqual(self.client.get('/api/jobs/not-a-job').status_code, 404)
        self.assertEqual(self.client.post('/api/topology', headers={'origin': 'https://different.example'}, content=b'bad').status_code, 403)

    def test_options_reject_wrong_types_and_oversized_runs(self):
        stock = inventory()
        validate_inventory(stock)
        for option in [{'piece_cap': True}, {'piece_cap': 1.5}, {'tolerance': float('nan')}, {'up': 'wrong'}, {'symmetry': 'bad'}]:
            with self.assertRaises(ValueError):
                validate_options(option, stock)
        for part in stock['parts']:
            part['quantity'] = 1000
        with self.assertRaisesRegex(ValueError, '5,000'):
            validate_options({}, stock)
        self.assertEqual(validate_options({'piece_cap': 500}, stock)['piece_cap'], 500)

if __name__ == '__main__':
    unittest.main()
