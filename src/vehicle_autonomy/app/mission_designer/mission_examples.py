"""Load versioned Mission examples as definitions only; never publish or execute."""
import json

from vehicle_autonomy._resources import resource_root


FILES = ('01_state_survey.json', '02_disarmed_branch.json', '03_ground_patrol.json',
         '04_air_hover_land.json', '05_air_survey_return.json', '06_runway_inspection.json')


def examples(target, kind):
    folder = resource_root()/'simulation/missions/examples'
    result = []
    for name in FILES:
        definition = json.loads((folder/name).read_text())
        if kind not in definition['supported_vehicles']:
            continue
        definition['target'] = target
        result.append(definition)
    return result
