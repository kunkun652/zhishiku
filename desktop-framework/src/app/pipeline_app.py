"""Production application entry with the additive knowledge processing pipeline."""
from . import main as backend
from .pipeline_api import install

app = backend.app
install(backend)
