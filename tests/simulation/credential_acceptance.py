"""Targeted real Rover/Copter signing/control and post-exit credential checks."""
import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from tests.simulation.harness import StageRunner, stamp
from tests.simulation.launch import ROOT


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    runner = StageRunner(root, total_timeout=900)
    report = dict(passed=False, started_at=stamp(), vehicles={})
    for kind in ('rover', 'copter'):
        stage = root / kind
        status = runner.run_stage(kind, [sys.executable, '-m', 'tests.simulation.phase1_probe',
            '--kind', kind, '--allow-send', '--review-remediation', '--run-dir', str(stage)],
            stage_dir=stage, timeout=420)
        result = json.loads((stage/'summary.json').read_text()) if (stage/'summary.json').exists() else {}
        manifest = json.loads((stage/'manifest.json').read_text()) if (stage/'manifest.json').exists() else {}
        proof = json.loads((stage/'signing-support.json').read_text()) if (stage/'signing-support.json').exists() else {}
        control = result.get('remediation', {}).get('normal_continuous_arm_disarm', {})
        resources = manifest.get('owned_credential_resources', [])
        no_state = bool(resources) and all(not (stage/r['name']).exists() for r in resources)
        no_private = not any(stage.rglob('*.private'))
        independent = proof.get('independent_pymavlink_verified') is True
        qualified = {f['type'] for f in proof.get('frames', [])} >= {'HEARTBEAT', 'COMMAND_ACK'}
        destruction = manifest.get('credential_destruction', [])
        record = dict(passed=False, stage_passed=status['passed'] and result.get('passed') is True,
            normal_arm_disarm=control, independent_signatures=independent and qualified,
            state_removed=no_state, private_removed=no_private, credentials_removed=manifest.get('credentials_removed'),
            destroyed_eeprom=sum(Path(f['path']).name=='eeprom.bin' for f in destruction),
            ports_released=manifest.get('ports_released'), remaining_process_groups=manifest.get('remaining_process_groups'),
            wrap_replay=result.get('remediation', {}).get('wraparound_replay'),
            writer_calls=len(result.get('writer_attempts', [])))
        record['passed'] = bool(record['stage_passed'] and control.get('passed') and record['independent_signatures']
            and no_state and no_private and record['credentials_removed'] and record['destroyed_eeprom'] == 1
            and record['ports_released'] and record['remaining_process_groups'] == [] and record['writer_calls'] > 0)
        report['vehicles'][kind] = record
        print(kind + ': ' + ('PASS' if record['passed'] else 'FAIL'), flush=True)
    report['passed'] = all(v['passed'] for v in report['vehicles'].values())
    report['ended_at'] = stamp()
    (root/'summary.json').write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send', action='store_true')
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error('--allow-send required for newly owned loopback simulations')
    result = run((args.run_dir or ROOT/'artifacts/phase1-credential-cleanup'/('real-'+uuid4().hex[:8])).resolve())
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
