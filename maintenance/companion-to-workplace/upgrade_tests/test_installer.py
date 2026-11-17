import importlib.util,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upgrade',ROOT/'upgrade.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
class InstallerTests(unittest.TestCase):
 def fixture(self,t):
  p=Path(t)/'installed';shutil.copytree(ROOT/'upgrade_tests'/'baseline',p);(p/'data').mkdir();(p/'data/history.sqlite3').write_bytes(b'preserve history');(p/'web/style.css').write_text('/* user custom skin */')
  runtime=p/'workhorse/runtime.py';runtime.write_text(runtime.read_text().replace('You are Workhorse, a local work agent.','You are my customized assistant.'));return p
 def test_install_preserve_and_rollback(self):
  with tempfile.TemporaryDirectory() as t:
   p=self.fixture(t);before={f.relative_to(p).as_posix():f.read_bytes() for f in p.rglob('*') if f.is_file()}
   with patch('builtins.print'):u.install(p,True)
   self.assertEqual((p/'data/history.sqlite3').read_bytes(),before['data/history.sqlite3']);self.assertEqual((p/'web/style.css').read_bytes(),before['web/style.css']);self.assertIn('You are my customized assistant.',(p/'workhorse/runtime.py').read_text());self.assertIn('/workplace.js',(p/'web/index.html').read_text());self.assertTrue((p/'launcher/Workhorse.cs').exists())
   u.restore(p,sorted((p/'backups').glob('workplace-*'))[-1])
   for name,raw in before.items():self.assertEqual((p/name).read_bytes(),raw,name)
 def test_conflict_refused(self):
  with tempfile.TemporaryDirectory() as t:
   p=self.fixture(t);f=p/'web/app.js';f.write_text('custom unknown application');before=f.read_bytes()
   with self.assertRaises(ValueError):u.install(p,True)
   self.assertEqual(f.read_bytes(),before);self.assertFalse((p/'workhorse/workplace.py').exists())
 def test_health_failure_restores(self):
  with tempfile.TemporaryDirectory() as t:
   p=self.fixture(t);before=(p/'server.py').read_bytes()
   with patch.object(u,'smoke',side_effect=['ok',ValueError('failed')]),patch('builtins.print'):
    with self.assertRaises(ValueError):u.install(p,True)
   self.assertEqual((p/'server.py').read_bytes(),before);self.assertFalse((p/'workhorse/workplace.py').exists())
 def test_later_edits_protected(self):
  with tempfile.TemporaryDirectory() as t:
   p=self.fixture(t)
   with patch('builtins.print'):u.install(p,True)
   f=p/'server.py';f.write_text(f.read_text()+'\n# later edit\n')
   with self.assertRaisesRegex(ValueError,'Later edits'):u.restore(p,sorted((p/'backups').glob('workplace-*'))[-1])
if __name__=='__main__':unittest.main()
