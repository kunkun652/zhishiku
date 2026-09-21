"""Production composition root. Legacy endpoints remain in app.main unchanged."""
from . import main as core
from .knowledge_pipeline.api import install

pipeline = install(core)
app = core.app
