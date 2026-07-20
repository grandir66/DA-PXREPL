"""Test modello NasSyncJob."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from services.nas_sync.models import NasSyncJob


def test_nas_sync_job_table_create_and_insert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    job = NasSyncJob(
        name="test",
        source_endpoint_id=1,
        dest_endpoint_id=2,
        source_paths=["/SHARE/docs"],
        dest_base_path="/share/DATI",
    )
    db.add(job)
    db.commit()
    row = db.query(NasSyncJob).first()
    assert row.name == "test"
    assert row.sync_method == "auto"
    assert row.delete_on_dest is False
    assert row.exclude_presets == []
    assert row.run_state == {}
    db.close()
