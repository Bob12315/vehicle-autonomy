"""One fresh owned fixture: Chrome-created Mission, then real manual control."""
import argparse
import json
from pathlib import Path
from tests.simulation.launch import install_signal_cleanup
from tests.simulation.mission_fixture import MissionFixture
from tests.simulation.mission_browser import exercise
from tests.simulation.mission_physics import mission_result


def run(path,kind):
    f=MissionFixture(path,kind);result=dict(passed=False,kind=kind)
    try:
        f.start()
        from vehicle_autonomy.app.web.mission_control import MissionControl
        result['vehicle_journal_binding']=[]
        for same_directory,alias in [(True,kind),(True,kind+'-alias'),(False,kind),(False,kind+'-alias')]:
            directory=f.path/'application' if same_directory else f.path/('alternate-'+alias)
            try:
                second=MissionControl({alias:f.driver},directory)
            except (ValueError,OSError) as exc:
                result['vehicle_journal_binding'].append(dict(same_directory=same_directory,target=alias,rejected=True,reason=str(exc)))
            else:
                second.close();raise AssertionError('same actual vehicle got a second journal/alias owner')
            if f.writer or not f.driver.info()['connected']:raise AssertionError('failed assembly affected live owner or wrote a vehicle command')
        exercise(f,result)
        result['mission_physical']=mission_result(f,result)
        result.update(passed=True,writer=f.writer,writer_calls=len(f.writer),state=f.api('/api/studio/state'))
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if f.lab:result.update(state=f.lab.handle('studio.state',{}),writer=f.writer)
        raise
    finally:
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kind',choices=('rover','copter','plane'),required=True);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();install_signal_cleanup();r=run(a.run_dir.resolve(),a.kind);print(a.kind,'Chrome Mission/Manual',r['passed'],flush=True)
if __name__=='__main__':main()
