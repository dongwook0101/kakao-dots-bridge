#!/usr/bin/env python3
"""Build the attributed business-only kmsg fork. Never grants permissions or sends."""
from pathlib import Path
import shutil
import subprocess

base=Path(__file__).resolve().parents[1]
vendor=base/'vendor/kmsg'
subprocess.run(['swift','build','-c','release','--package-path',str(vendor)],check=True)
directory=subprocess.check_output(['swift','build','-c','release','--package-path',str(vendor),'--show-bin-path'],text=True).strip()
(base/'bin').mkdir(exist_ok=True)
shutil.copy2(Path(directory)/'kmsg',base/'bin/kmsg-work')
print('Optional sender built. Sending remains disabled until explicitly configured and approved.')
