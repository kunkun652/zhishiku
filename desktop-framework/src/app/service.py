"""Production composition root. Legacy endpoints remain in app.main unchanged."""
from . import main as core
from .knowledge_pipeline.api import install

pipeline = install(core)
from .workbench import install as install_workbench
install_workbench(core, pipeline)
from .access import install as install_access
install_access(core)
app = core.app
