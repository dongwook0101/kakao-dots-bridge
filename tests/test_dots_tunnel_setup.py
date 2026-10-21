import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

path=Path(__file__).resolve().parents[1]/'scripts/connect_dots_tunnel.py'
spec=importlib.util.spec_from_file_location('dots_tunnel_setup',path);setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)


class TunnelSetupTests(unittest.TestCase):
    def test_secret_is_private_and_never_in_process_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);secret=base/'runtime/dots-tunnel-key';secret.parent.mkdir()
            value='sk-sensitive-runtime-test'
            setup.private_key_file(secret,lambda prompt:value)
            self.assertEqual(secret.stat().st_mode&0o777,0o600)
            command=setup.connect_command(base,'tunnel_test_12345678')
            self.assertNotIn(value,' '.join(command));self.assertIn('file:'+str(secret),command)
            self.assertNotIn('responses',' '.join(command))
    def test_existing_symlink_or_public_key_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);target=base/'target';target.write_text('sk-test');target.chmod(0o644)
            alias=base/'link';alias.symlink_to(target)
            for path in (target,alias):
                with self.assertRaises(ValueError):setup.private_key_file(path,lambda prompt:self.fail('Must not read a key'))
    def test_tunnel_id_cannot_inject_shell_arguments(self):
        with self.assertRaises(ValueError):setup.connect_command(Path('/tmp'), 'tunnel_bad;command')


if __name__=='__main__':unittest.main()
