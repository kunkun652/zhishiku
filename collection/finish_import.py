"""Finalize source catalog only after bulk ingestion exits successfully."""
import json,time
from pathlib import Path
from build_cards import run as cards
from organize import run as organize
from ingest import BASE,kb
while not (BASE/'import-report.json').exists():time.sleep(5)
cards();organize()
print(json.dumps(kb.collection(),ensure_ascii=False),flush=True)
