"""Real HTTP Job + real VehicleActionDriver: Mission UNKNOWN is not fallback."""
import argparse
import json
from pathlib import Path
from threading import Thread

from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.actions.external.clients import ApiJob
from vehicle_autonomy.app.bootstrap.external_actions import initialize_http_resources
from vehicle_autonomy.contracts.action import ActionKind,ActionResource,ActionSafety
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect,ModeEffect
from tests.simulation.external_actions import JobServer
from tests.simulation.round3_boundaries import active,endpoint,proof
from tests.simulation.launch import install_signal_cleanup
from tests.simulation.phase4_faults import until,denied
from tests.simulation.mission_fixture import MissionFixture


def run(path):
    f=MissionFixture(path,'rover');server=None;result=dict(passed=False,cases=[])
    try:
        f.start();server=JobServer();thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        store=initialize_http_resources(path/'http-provider',endpoint(server),lambda:proof(server))
        class Instance:
            sent=False
            def __init__(self,positive,emit,timeout):
                self.positive=positive;self.emit=emit;self.timeout=timeout
                self.job=ApiJob(endpoint(server),dict(duration_s=.3 if positive else 20.,behavior='normal'))
            def tick(self,world):return self.tick_with_results(world,())
            def tick_with_results(self,world,results):
                status=self.job.poll()
                configured=not self.emit or bool(results and results[-1].phase.value=='COMPLETED')
                if self.positive and status['state']=='SUCCEEDED' and configured:return ActionDecision(ActionOutcome.SUCCEEDED,result={'external_trusted_terminal':True})
                effects=(ModeEffect('HOLD'),) if self.emit and not self.sent else ();self.sent=True
                return ActionDecision(ActionOutcome.RUNNING,effects,feedback=status)
            def exit(self,*args):
                if self.positive:return ExitDecision(True)
                if self.timeout:return ExitDecision(False)
                raise RuntimeError('real Job still running; external exit response lost')
        class Factory:
            resource_store=store;positive=False;emit=False;timeout=False
            def start(self,*args):return Instance(self.positive,self.emit,self.timeout)
        factory=Factory()
        # This test composes the existing mode contract; the generic ActionSpec
        # default (1 s) is not SetMode's audited 5 s configuration deadline.
        mode_ttl=f.lab.registry.resolve_typed('SetMode').spec.effect_ttl_ns
        f.lab.registry.register_typed(ActionSpec('MixedJob',Empty,kind=ActionKind.GOAL,effect_types=(ArmEffect,ModeEffect),
            effect_ttl_overrides={'ModeEffect':mode_ttl},
            external_lifecycle='managed',resources=(ActionResource('vehicle.motion',conflict_group='vehicle.control'),ActionResource('ai.inference'))),factory)
        for index,(emit,timeout) in enumerate(((False,False),(True,True)),1):
            factory.positive=False;factory.emit=emit;factory.timeout=timeout
            spec=dict(schema_version=1,id='mixed-negative-'+str(index),name='mixed',version='1.0.0',target='rover',root='fallback',timeout_s=40,
                nodes=[dict(id='fallback',type='Fallback',children=['deadline','recovery']),dict(id='deadline',type='Timeout',timeout_s=3 if emit else .7,children=['job']),
                    dict(id='job',type='Action',action='MixedJob',parameters={}),dict(id='recovery',type='Action',action='MixedJob',parameters={})])
            writer_before=len(f.writer);jobs_before=len(server.jobs)
            r=f.api('/api/missions/start',dict(spec=spec,allow_send=True))
            until(f,lambda:active(server)==1,4)
            value=f.wait_mission(r['id'],state='UNKNOWN',timeout=15)
            a=f.lab.runtime.view(value['action_ids'][0])
            if len(server.jobs)!=jobs_before+1 or active(server)!=1:raise AssertionError('fallback created a second actual Job')
            if len(value['action_ids'])!=1 or value['release_safe']:raise AssertionError('uncertain mixed Mission advanced/released')
            # Exit timeout publishes UNKNOWN before the already queued Driver
            # finish future necessarily resolves. Observe the independent proof
            # explicitly; absence is never evidence of safety. This wait does
            # not extend Action/Execution exit deadlines or release resources.
            vehicle_guard=until(f,lambda:(g if (g:=f.driver.guard_status(a['id'])) is not None and g.release_safe else None),2)
            if active(server)!=1 or f.lab.missions.view(r['id'])['release_safe']:
                raise AssertionError('external responsibility lost while waiting for independent vehicle proof')
            if len(f.writer)-writer_before!=int(emit):raise AssertionError('unexpected real vehicle Writer count')
            f.pause(.8)
            if f.lab.missions.view(r['id'])['release_safe']:raise AssertionError('later tick/Driver safety cleared external responsibility')
            before=len(f.writer);denied(f,'/api/manual/action',dict(name='Arm',target='rover',parameters={},allow_send=True))
            raw=f.lab.runtime.submit('MixedJob','rover',allow_send=True)
            if raw['state']!='REJECTED' or len(server.jobs)!=jobs_before+1 or len(f.writer)!=before:
                raise AssertionError('same resource conflict started an actual job/Writer')
            until(f,lambda:active(server)==0,25)
            until(f,lambda:f.lab.missions.view(r['id'])['release_safe'],5)
            if f.lab.missions.view(r['id'])['state']!='UNKNOWN':raise AssertionError('old unknown rewritten as success')
            factory.positive=True
            positive=dict(schema_version=1,id='mixed-positive-'+str(index),name='positive',version='1.0.0',target='rover',root='job',timeout_s=15,
                nodes=[dict(id='job',type='Action',action='MixedJob',parameters={})])
            q=f.api('/api/missions/start',dict(spec=positive,allow_send=True));normal=f.wait_mission(q['id'],timeout=18)
            if len(server.jobs)!=jobs_before+2 or active(server)!=0 or not normal['release_safe']:
                raise AssertionError('trusted terminal failed to restore normal execution')
            result['cases'].append(dict(emit=emit,exit_timeout=timeout,unknown=a,mission=value,normal=normal,
                actual_jobs_started=2,actual_active_during_unknown=1,vehicle_exit_independently_safe=True,
                vehicle_exit_evidence=dict(release_safe=vehicle_guard.release_safe,reason=vehicle_guard.reason),
                negative_writer_calls=int(emit),rejected_new_writer_calls=0))
        result.update(passed=True,mode_effect_ttl_from_standard_ns=mode_ttl,writer=f.writer,state=f.api('/api/studio/state'))
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:
            f.close()
            if server:server.shutdown();thread.join(3);server.server_close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup();v=run(a.run_dir.resolve());print('Mission mixed external',v['passed'],flush=True)
if __name__=='__main__':main()
