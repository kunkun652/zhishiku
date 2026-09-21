"""Run legacy module-scoped fixtures in separate processes, preserving assertions."""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
modules=('test_framework','test_knowledge_pipeline','test_knowledge_runtime',
         'test_pipeline_main_integration','test_workbench','test_trusted_workbench')
results=[]
with (root/'evidence/trusted-tests.log').open('w',encoding='utf-8') as log:
    for name in modules:
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root/'tests'),'-p',name+'.py','-v'],
                              cwd=root.parent,capture_output=True,text=True,encoding='utf-8')
        log.write(name+'\n'+result.stdout+result.stderr+'\n')
        log.flush()
        results.append(result.returncode)
        print(name+': '+('PASS' if result.returncode==0 else 'FAIL'),flush=True)
raise SystemExit(1 if any(results) else 0)
