"""Finite named routes and object-inspection recipes above target navigation."""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
import tomllib


@dataclass(frozen=True,slots=True)
class AutonomyRecipe:
    name: str
    goals: tuple[str,...]
    total_timeout_s: float
    inspection_label: str | None = None
    inspection_at: str | None = None


class RecipeCatalog:
    def __init__(self,path,goals):
        self.path=Path(path);raw=self.path.read_bytes()
        if len(raw)>32768:raise ValueError('recipe catalog exceeds size bound')
        self.sha256=hashlib.sha256(raw).hexdigest();d=tomllib.loads(raw.decode())
        if set(d)!={'schema','recipes'} or type(d['schema']) is not int or d['schema']!=1 or type(d['recipes']) is not list or not 1<=len(d['recipes'])<=32:
            raise ValueError('invalid autonomy recipes')
        self.recipes={}
        for r in d['recipes']:
            if type(r) is not dict or set(r)-{'name','goals','total_timeout_s','inspection_label','inspection_at'} or not {'name','goals','total_timeout_s'}<=set(r):
                raise ValueError('invalid recipe fields')
            name=r['name'];route=r['goals'];deadline=r['total_timeout_s']
            if type(name) is not str or re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,47}',name) is None or name in self.recipes:
                raise ValueError('invalid recipe name')
            if type(route) is not list or not 1<=len(route)<=8 or any(type(n) is not str or n not in goals.goals for n in route):
                raise ValueError('recipe requires 1..8 registered navigation goals')
            if type(deadline) not in (int,float) or not math.isfinite(deadline) or not 1<=deadline<=600:
                raise ValueError('recipe deadline must be within 1..600 seconds')
            label,at=r.get('inspection_label'),r.get('inspection_at')
            if (label is None)!=(at is None) or (label is not None and (type(label) is not str or not label or at not in route)):
                raise ValueError('inspection needs a label and a registered route checkpoint')
            self.recipes[name]=AutonomyRecipe(name,tuple(route),deadline,label,at)

    def check(self):
        if hashlib.sha256(self.path.read_bytes()).hexdigest()!=self.sha256:
            raise ValueError('autonomy_recipe_catalog_changed')
