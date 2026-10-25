"""Build and inspect an independently installed Mission wheel, without vehicles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile


def installed(root):
    import vehicle_autonomy
    from vehicle_autonomy._resources import resource_root
    from vehicle_autonomy.engine.action.registry import ActionRegistry
    from vehicle_autonomy.actions.catalog import register_standard
    from vehicle_autonomy.app.web import mission_control
    package = Path(vehicle_autonomy.__file__).resolve()
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        raise AssertionError('wheel check imported the checkout')
    resources = resource_root()
    registry = ActionRegistry(); register_standard(registry)
    if 'rclpy' in sys.modules:
        raise AssertionError('optional ROS imported by the application')
    static = Path(mission_control.__file__).parent / 'static'
    assets = ['mission-studio.html', 'mission-studio.js', 'manual-control.html',
              'manual-control.js', 'mission-api.js', 'mission-ui.css', 'action-lab.html']
    for name in assets:
        if not (static / name).is_file():
            raise AssertionError('missing installed Web asset: ' + name)
    for kind in ('rover', 'copter', 'plane'):
        if not (resources / 'simulation/missions' / (kind + '.json')).is_file():
            raise AssertionError('missing installed Mission template')
    cli = None
    token_path = root / 'token'
    stdout=(root/'cli-stdout.log').open('w')
    stderr=(root/'cli-stderr.log').open('w')
    try:
        cli = subprocess.Popen([str(Path(sys.prefix) / 'bin/vehicle-autonomy-missions'),
            '--token-file', str(token_path), '--data-dir', str(root / 'application'), '--port', '0'],
            stdout=stdout, stderr=stderr, text=True)
        match=None;end=time.monotonic()+8
        while time.monotonic()<end:
            match=re.search(r'http://127.0.0.1:\d+', (root/'cli-stdout.log').read_text())
            if match or cli.poll() is not None:break
            time.sleep(.1)
        if not match:
            raise AssertionError('installed Mission entry failed to start')
        token = token_path.read_text().strip()
        def get(route):
            with urlopen(Request(match.group() + route,
                    headers={'Authorization': 'Bearer ' + token}), timeout=3) as response:
                return response.read()
        if json.loads(get('/api/vehicles')) != {'ok': True, 'result': []}:
            raise AssertionError('default installation opened a vehicle')
        state = json.loads(get('/api/studio/state'))['result']
        for route, marker in [('/studio', b'mission-studio.js'),
                              ('/control', b'manual-control.js'), ('/', b'action-lab.js')]:
            if marker not in get(route):
                raise AssertionError('installed UI route unavailable: ' + route)
        # Starting the CLI does not initialize an unrelated provider registry.
        return dict(passed=True, installed_package=str(package), resource_root=str(resources),
                    catalog_entries=len(registry.catalog()), default_vehicles=0,
                    served_routes=['/', '/studio', '/control'], optional_ros_imported=False)
    finally:
        if cli and cli.poll() is None:
            cli.send_signal(signal.SIGTERM)
            try: cli.wait(timeout=5)
            except subprocess.TimeoutExpired: cli.kill(); cli.wait(timeout=3)
        token_path.unlink(missing_ok=True)
        stdout.close();stderr.close()


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    checkout = Path(__file__).resolve().parents[2]
    result = {'passed': False}
    try:
        with (root / 'build.log').open('w') as log:
            subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(checkout), '--no-deps',
                '--no-build-isolation', '--wheel-dir', str(root / 'dist')], check=True, stdout=log, stderr=log)
        wheel, = (root / 'dist').glob('*.whl')
        # Verify every Python module, Web asset and declared installed resource.
        try: import tomllib
        except ImportError: import tomli as tomllib
        config = tomllib.loads((checkout / 'pyproject.toml').read_text())
        verified = []
        with ZipFile(wheel) as archive:
            for path in (checkout / 'src/vehicle_autonomy').rglob('*'):
                if path.is_file() and (path.suffix == '.py' or 'static' in path.parts):
                    relative = str(path.relative_to(checkout / 'src'))
                    if archive.read(relative) != path.read_bytes():
                        raise AssertionError('wheel/source mismatch: ' + relative)
                    verified.append(relative)
            for destination, paths in config['tool']['setuptools']['data-files'].items():
                for name in paths:
                    suffix = '.data/data/' + destination + '/' + Path(name).name
                    matches = [n for n in archive.namelist() if n.endswith(suffix)]
                    if len(matches) != 1 or archive.read(matches[0]) != (checkout / name).read_bytes():
                        raise AssertionError('installed resource mismatch: ' + name)
                    verified.append(name)
        venv = root / 'venv'
        subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(venv)], check=True)
        python = venv / 'bin/python'
        with (root / 'install.log').open('w') as log:
            subprocess.run([str(python), '-m', 'pip', 'install', str(wheel) + '[mavlink]'],
                check=True, stdout=log, stderr=log)
        env = dict(os.environ); env.pop('PYTHONPATH', None); env.pop('VAF_RESOURCE_ROOT', None)
        child = subprocess.run([str(python), str(Path(__file__).resolve()), '--installed', '--run-dir', str(root)],
            cwd=root, env=env, capture_output=True, text=True, timeout=45)
        (root / 'installed.log').write_text(child.stdout + child.stderr)
        if child.returncode:
            raise AssertionError('installed check failed; see installed.log')
        result.update(json.loads(child.stdout.strip().splitlines()[-1]))
        result.update(wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                      verified_source_and_resource_files=verified, independent_working_directory=True)
    except BaseException as exc:
        result.update(passed=False, error=type(exc).__name__ + ': ' + str(exc))
    finally:
        (root / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--installed', action='store_true')
    args = parser.parse_args()
    result = installed(args.run_dir.resolve()) if args.installed else run(args.run_dir.resolve())
    print(json.dumps(result if args.installed else {
        'passed': result['passed'], 'error': result.get('error'),
        'verified_files': len(result.get('verified_source_and_resource_files', [])),
        'summary': str(args.run_dir / 'summary.json')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
