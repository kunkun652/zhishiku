"""Worker lifecycle tests. Protocol fixtures, NOT real Semantica/model inference."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app.knowledge_pipeline.runtime import Runtime
from app.knowledge_pipeline.contracts import VERSION

# A real child process with a deliberately fake model-protocol implementation.
WORKER = '''import json,os,sys
from pathlib import Path
request=json.loads(Path(sys.argv[1]).read_text('utf-8'))
result={'protocol': %r, 'semantica_version':'TEST_FIXTURE', 'status':'ready',
        'action':request['action'], 'proxy_present':any(k in os.environ for k in
        ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'))}
Path(sys.argv[2]).write_text(json.dumps(result),'utf-8')
''' % VERSION


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zh-runtime-tests-')
        self.runtime = Runtime(Path(self.temp.name))
        self.command = patch.object(self.runtime, 'command', return_value=[sys.executable, '-c', WORKER])
        self.command.start()
    def tearDown(self):
        self.runtime.close()
        self.command.stop()
        self.temp.cleanup()

    def test_01_successful_subprocess_and_cleanup(self):
        result = self.runtime.call('probe', {})
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['action'], 'probe')
        self.assertFalse(self.runtime.lock.locked())
        self.assertIsNone(self.runtime.process)
        self.assertFalse(list((Path(self.temp.name)/'pipeline-runtime').glob('request-*')))

    def test_02_directory_failure_releases_lock_and_allows_retry(self):
        with patch('app.knowledge_pipeline.runtime.Path.mkdir', side_effect=PermissionError('fixture read-only directory')):
            with self.assertRaises(PermissionError):
                self.runtime.call('probe', {})
        self.assertFalse(self.runtime.lock.locked())
        self.assertEqual(self.runtime.last['status'], 'failed')
        self.assertEqual(self.runtime.call('probe', {})['status'], 'ready')

    def test_03_reserved_action_cannot_be_overridden(self):
        with self.assertRaises(ValueError):
            self.runtime.call('probe', {'action': 'answer'})
        with self.assertRaises(ValueError):
            self.runtime.call('execute_shell', {})
        self.assertFalse(self.runtime.lock.locked())

    def test_04_closed_runtime_rejects_calls(self):
        self.runtime.close()
        with self.assertRaises(RuntimeError):
            self.runtime.call('probe', {})
        with patch.dict(os.environ, {'ZH_PIPELINE_MODEL': 'fixture'}):
            self.assertFalse(self.runtime.status()['configured'])

    def test_05_child_failure_releases_lock(self):
        with patch.object(self.runtime, 'command', return_value=[sys.executable, '-c', 'raise SystemExit(2)']):
            with self.assertRaises(RuntimeError):
                self.runtime.call('probe', {})
        self.assertFalse(self.runtime.lock.locked())
        self.assertIsNone(self.runtime.process)
        self.assertEqual(self.runtime.last['status'], 'failed')

    def test_06_concurrent_call_does_not_release_another_call_lock(self):
        self.runtime.lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                self.runtime.call('probe', {})
            self.assertTrue(self.runtime.lock.locked())
        finally:
            self.runtime.lock.release()

    def test_07_timeout_kills_and_reaps_child(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 180), 0]
        with patch('app.knowledge_pipeline.runtime.subprocess.Popen', return_value=process):
            with self.assertRaises(RuntimeError):
                self.runtime.call('probe', {})
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertIsNone(self.runtime.process)
        self.assertFalse(self.runtime.lock.locked())

    def test_08_probe_readiness_expires(self):
        self.runtime.last = {'status': 'ready'}
        self.runtime.probed_at = time.monotonic() - 301
        self.assertEqual(self.runtime.status()['last_probe']['status'], 'probe_expired')

    def test_09_shutdown_reaps_terminated_child(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 5), 0]
        self.runtime.process = process
        self.runtime.close()
        self.runtime.process = None
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_10_worker_does_not_inherit_proxy_variables(self):
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://fixture.invalid', 'ALL_PROXY': 'http://fixture.invalid'}):
            result = self.runtime.call('probe', {})
        self.assertFalse(result['proxy_present'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
