"""Actual authenticated Web -> Application -> disarmed Rover HOLD acceptance."""
from __future__ import annotations

import argparse
from contextlib import closing
import http.client
import json
from pathlib import Path
import socket
import sys
import time

from app.control import request
from tests.simulation.launch import OwnedSimulation, ROOT, install_signal_cleanup


def run(directory):
    directory.mkdir(parents=True,exist_ok=False)
    owned=OwnedSimulation(directory,'rover')
    result={'passed':False,'scope':'owned localhost disarmed HOLD only; no physical vehicle'}
    endpoint=directory/'app.sock'
    try:
        owned.start()
        profile=directory/'profile.toml'
        profile.write_text((ROOT/'simulation/profiles/rover.toml').read_text().replace('port = 5760',f'port = {owned.port}'))
        def launch(send,suffix):
            return owned.start_process('application'+suffix,[sys.executable,'-m','app.main','run','--profile','rover_sim',
                '--config',str(profile),'--control-socket',str(endpoint),*(['--allow-send'] if send else [])])
        def ready():
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                owned.assert_alive()
                if endpoint.exists():
                    state=request(endpoint,'status')['result']
                    if state['state']=='READY':return state
                time.sleep(.1)
            raise TimeoutError('application readiness')
        app=launch(True,'-send');state=ready()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        token_file=directory/'token'
        web=owned.start_process('web',[sys.executable,'-m','app.web','--control-socket',str(endpoint),
            '--port',str(port),'--data-dir',str(directory/'console'),'--token-file',str(token_file),'--missions','disarmed_mode'])
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and not token_file.exists():owned.assert_alive();time.sleep(.05)
        token=token_file.read_text().strip()
        def http(path,body=None,*,authenticated=True,csrf=True,rid='request'):
            headers={'Authorization':'Bearer '+token} if authenticated else {}
            if body is not None:
                headers.update({'Content-Type':'application/json','X-VAF-Request-ID':rid})
                if csrf:headers['X-VAF-CSRF']=token
            with closing(http.client.HTTPConnection('127.0.0.1',port,timeout=3)) as client:
                client.request('GET' if body is None else 'POST','/api/'+path,
                    None if body is None else json.dumps(body),headers)
                response=client.getresponse();return response.status,json.loads(response.read())
        while time.monotonic()<deadline:
            try:
                if http('status')[0]==200:break
            except OSError:time.sleep(.05)
        assert http('status',authenticated=False)[0]==401
        payload={'mission':'disarmed_mode','expected_session':state['session_id']}
        assert http('start',payload,csrf=False)[0]==403
        first=http('start',payload,rid='start-one');assert first[0]==200,first
        assert http('start',payload,rid='start-one')==first
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            current=http('status')[1]['result']
            if current['task'] and current['task']['status'] in ('SUCCEEDED','FAILED'):break
            time.sleep(.1)
        assert current['task']['status']=='SUCCEEDED',current['task']
        assert not current['vehicle']['armed'] and not current['system_send'] and not current['action_send']
        assert all(e['phase']=='COMPLETED' for e in current['task']['effects'].values())
        result['task_id']=current['task']['task_id'];result['effects']=current['task']['effects']
        assert request(endpoint,'shutdown')['ok'];assert app.wait(timeout=6)==0;owned.stop_process(app)
        app=launch(False,'-readonly-restart');new=ready();assert new['session_id']!=state['session_id']
        assert http('start',payload,rid='old-session')[0]==409
        assert http('start',{'mission':'disarmed_mode','expected_session':new['session_id']},rid='not-authorized')[0]==409
        assert not request(endpoint,'status')['result']['system_send']
        assert request(endpoint,'shutdown')['ok'];assert app.wait(timeout=6)==0;owned.stop_process(app)
        owned.stop_process(web)
        result.update(passed=True,checks=['bearer_auth','csrf','request_id_idempotence','typed_mode_ack_observation',
            'disarmed_send_revocation','restart_old_session_rejected','restart_readonly_no_authority'])
    except Exception as exc:
        result['error']=f'{type(exc).__name__}: {exc}'
    finally:
        try:owned.close()
        except Exception as exc:result.update(passed=False,cleanup_error=str(exc))
        (directory/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--allow-send',action='store_true')
    args=parser.parse_args()
    if not args.allow_send:parser.error('explicit localhost SEND required')
    install_signal_cleanup();result=run(args.run_dir.resolve());print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
