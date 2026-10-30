"""Explicit external World utility; no software is fetched at import or startup."""
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths

def main():
    """Local, isolated Gazebo world launcher. No autopilot commands are sent."""
    import argparse, json, os, pathlib, signal, subprocess, sys, tempfile, time, uuid, xml.etree.ElementTree as ET
    ROOT = resource_root()/'simulation/world_registry'
    HOST = HostEnvironment()
    ASSETS = HOST.path('legacy_assets')
    EVIDENCE = RuntimePaths().slot('sessions', 'world-registry')
    def source_path(relative):
        return ASSETS/relative.removeprefix('assets/') if relative.startswith('assets/') else ROOT/relative
    CATALOG = json.loads((ROOT / 'catalog.yaml').read_text())

    def env_for(partition=None):
        env = os.environ.copy()
        paths = [ASSETS/'adapter_models', ASSETS, ROOT.parent/'models', HOST.path('gazebo_plugin_root')/'models']
        env['GZ_SIM_RESOURCE_PATH'] = ':'.join(map(str, paths)) + ':' + env.get('GZ_SIM_RESOURCE_PATH', '')
        env['SDF_PATH'] = ':'.join(map(str, paths)) + ':' + env.get('SDF_PATH', '')
        env['GZ_SIM_SYSTEM_PLUGIN_PATH'] = str(HOST.path('gazebo_plugin_root')/'build')+':' + env.get('GZ_SIM_SYSTEM_PLUGIN_PATH', '')
        if partition: env['GZ_PARTITION'] = partition
        return env

    def run():
        p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
        sub.add_parser('list')
        for action in ('check','launch','smoke'):
            s=sub.add_parser(action); s.add_argument('id',choices=CATALOG['scenes']);
            if action != 'check':
                s.add_argument('--vehicle',help='model URI name; experimental, does not start SITL'); s.add_argument('--pose',default='0 0 0.3 0 0 0',help='six SDF pose values'); s.add_argument('--headless',action='store_true')
            if action=='smoke': s.add_argument('--seconds',type=float,default=60,help='target simulated seconds'); s.add_argument('--timeout',type=float,default=240,help='wall clock limit')
        a=p.parse_args()
        if a.cmd=='list':
            for key,info in CATALOG['scenes'].items(): print(key,info['name'], 'installed' if info.get('sdf') and source_path(info['sdf']).is_file() else 'missing')
            return 0
        info=CATALOG['scenes'][a.id]; path=source_path(info['sdf']) if info.get('sdf') else None
        if not path or not path.is_file(): print('Missing SDF / this entry is a launch reference:',file=sys.stderr); return 2
        if a.cmd=='check':
            missing=[]
            for uri in ET.parse(path).findall('.//mesh/uri'):
                value=(uri.text or '').strip()
                if value.startswith('model://'):
                    relative=value[len('model://'):]
                    roots=[ASSETS, ROOT.parent/'models', HOST.path('gazebo_plugin_root')/'models']
                    if not any((base/relative).exists() for base in roots): missing.append(value)
            if missing: print('Missing mesh files:', ', '.join(missing))
            try: result=subprocess.run([HOST.executable('gazebo') or 'gz','sdf','-k',str(path)],env=env_for(),capture_output=True,text=True,timeout=30)
            except subprocess.TimeoutExpired: print('SDF check timed out (possibly missing remote resources)'); return 2
            print(result.stdout,result.stderr); return result.returncode or (1 if missing else 0)
        if a.cmd=='smoke' and (a.seconds<=0 or a.timeout<=0): p.error('seconds and timeout must be positive')
        partition='vaf-world-'+uuid.uuid4().hex; env=env_for(partition); temp=None
        (EVIDENCE).mkdir(parents=True,exist_ok=True)
        if a.vehicle:
            if len(a.pose.split())!=6: p.error('pose requires six numbers')
            try: [float(x) for x in a.pose.split()]
            except ValueError: p.error('pose requires numeric values')
            if not a.vehicle.replace('_','').replace('-','').isalnum(): p.error('invalid model name')
            tree=ET.parse(path); world=tree.getroot().find('world'); inc=ET.SubElement(world,'include'); ET.SubElement(inc,'uri').text='model://'+a.vehicle; ET.SubElement(inc,'pose').text=a.pose
            temp=tempfile.NamedTemporaryFile(suffix='.sdf',delete=False,dir=EVIDENCE); temp.close(); tree.write(temp.name,encoding='unicode'); path=pathlib.Path(temp.name)
        out=EVIDENCE/(a.id+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]); out.mkdir(parents=True)
        cmd=[HOST.executable('gazebo') or 'gz','sim','-r','-v','3'];
        if a.headless or a.cmd=='smoke': cmd += ['-s','--headless-rendering']
        cmd += [str(path)]; started=time.monotonic(); log=(out/'gazebo.log').open('w'); proc=None
        try:
            proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            print('Log:',out, 'partition:',partition,flush=True)
            if a.cmd=='launch': return proc.wait()
            samples=[]; maximum=0.; status='FAIL'
            while time.monotonic()-started<a.timeout and proc.poll() is None:
                try:
                    r=subprocess.run([HOST.executable('gazebo') or 'gz','topic','-e','-t','/stats','-n','1'],env=env,capture_output=True,text=True,timeout=5)
                    import re
                    match=re.search(r'sim_time\s*\{\s*sec:\s*(\d+)(?:\s*nsec:\s*(\d+))?',r.stdout)
                    if match:
                        sim=int(match.group(1))+int(match.group(2) or 0)/1e9; maximum=max(maximum,sim)
                        usage=subprocess.run(['ps','-p',str(proc.pid),'-o','%cpu=,rss='],capture_output=True,text=True).stdout.strip()
                        samples.append({'wall_seconds':round(time.monotonic()-started,2),'sim_seconds':sim,'process_cpu_percent_and_rss_kib':usage,'raw':r.stdout})
                        if sim>=a.seconds: status='PASS'; break
                except subprocess.TimeoutExpired: pass
                time.sleep(2)
            log.flush()
            import re
            content=re.sub(r'\x1b\[[0-9;]*m','', (out/'gazebo.log').read_text(errors='replace'))
            errors=[line for line in content.splitlines() if '[Err]' in line or 'Failed to load' in line or 'Unable to find uri' in line]
            if errors: status='FAIL'
            result={'status':status,'sim_seconds':maximum,'wall_seconds':round(time.monotonic()-started,2),'samples':samples,'process_exit':proc.poll(),'error_lines':errors[:30],'note':'Time advancement and obvious error scan only; review gazebo.log. This is not vehicle or SITL acceptance.'}
            (out/'result.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2)); return 0 if status=='PASS' else 1
        finally:
            if proc and proc.poll() is None:
                os.killpg(proc.pid,signal.SIGINT)
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); proc.wait()
            log.close()
            if temp: pathlib.Path(temp.name).unlink(missing_ok=True)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
