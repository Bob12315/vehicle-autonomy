"""Migration checks for executable imports and resource lookup from another cwd."""
import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from vehicle_autonomy._resources import resource_root


class PackageLayoutTests(unittest.TestCase):
    def test_moved_modules_are_unique_and_import_without_ros(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'docs/architecture_migration_files.json').read_text())
        old_roots = {p.split('/')[0] for p in manifest['moved']}
        self.assertFalse((root / 'legacy').exists())
        self.assertEqual({p.name for p in (root / 'src/vehicle_autonomy').iterdir() if p.is_dir() and p.name != '__pycache__'},
                         {'contracts', 'engine', 'actions', 'vehicles', 'world', 'autonomy', 'app'})
        for old, new in manifest['moved'].items():
            self.assertFalse((root / old).exists(), old)
            path = root / new
            self.assertTrue(path.is_file(), new)
            if new.endswith('.py'):
                name = new.removeprefix('src/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')
                importlib.import_module(name)
                for node in ast.walk(ast.parse(path.read_text())):
                    modules = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                               [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                    self.assertFalse(any(m.split('.')[0] in old_roots for m in modules), new)
        self.assertNotIn('rclpy', sys.modules)

    def test_safe_defaults_and_resources_from_foreign_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'vehicle_autonomy.app.cli', 'status'], cwd=directory,
                                    capture_output=True, text=True, check=True)
            self.assertFalse(json.loads(result.stdout)['send_commands'])
            result = subprocess.run([sys.executable, '-m', 'vehicle_autonomy.app.bootstrap.hardware', '--check'],
                                    cwd=directory, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), {'valid': True, 'mode': 'hardware_readonly', 'system_send': False, 'action_send': False})
            profile = json.loads((resource_root() / 'configs/deployment/hardware-controlled.json').read_text())
            path = Path(directory) / 'controlled.json'
            path.write_text(json.dumps(profile))
            result = subprocess.run([sys.executable, '-m', 'vehicle_autonomy.app.bootstrap.hardware', '--check', '--config', str(path)],
                                    cwd=directory, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('hardware control is unimplemented; onsite independent safety acceptance required', result.stderr)
