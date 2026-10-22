"""Remove incompatible inherited extras in a dedicated deployment container only.

The complete resolved target dependency closure is protected. Any conflict in
that closure is an error; this script cannot hide it by uninstalling the target.
"""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

lock = Path(sys.argv[1])
keep = {canonicalize_name(line.split('==')[0]) for line in lock.read_text().splitlines()
        if '==' in line and not line.lstrip().startswith('#')}
installed = {canonicalize_name(d.metadata['Name']): d for d in metadata.distributions()}
remove = set()
reasons = {}
for name, distribution in installed.items():
    for raw in distribution.requires or []:
        requirement = Requirement(raw)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        dependency = installed.get(canonicalize_name(requirement.name))
        if dependency is None or not requirement.specifier.contains(dependency.version, prereleases=True):
            remove.add(name)
            reasons[name] = raw
while True:
    previous = set(remove)
    for name, distribution in installed.items():
        for raw in distribution.requires or []:
            requirement = Requirement(raw)
            if ((not requirement.marker or requirement.marker.evaluate())
                    and canonicalize_name(requirement.name) in remove):
                remove.add(name)
                reasons[name] = raw
    if previous == remove:
        break
if remove & keep:
    raise RuntimeError(f'Resolved target conflict; refusing removal: {sorted(remove & keep)}')
record = {'removed_inherited_extras': sorted(remove), 'reasons': reasons,
          'protected_target_count': len(keep)}
Path('/work/inherited-extras-removal.json').write_text(json.dumps(record, indent=2))
if remove:
    subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', *sorted(remove)], check=True)
print(json.dumps(record), flush=True)
