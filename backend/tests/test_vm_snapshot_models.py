"""Test modello VmSnapshotJob."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from services.vm_snapshot.models import VmSnapshotJob


def test_vm_snapshot_job_table_create_and_insert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    job = VmSnapshotJob(
        name="snap-prod",
        label="daily",
        keep=7,
        targets=[{"node_id": 1, "vmid": 100, "vm_type": "qemu", "name": "web01"}],
        selectors={"tags": ["prod"], "node_ids": [], "exclude_vmids": []},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    row = db.query(VmSnapshotJob).first()
    assert row.name == "snap-prod"
    assert row.label == "daily"
    assert row.keep == 7
    assert row.include_vmstate is False
    assert row.targets[0]["vmid"] == 100
    assert row.selectors["tags"] == ["prod"]
    assert row.notify_mode == "failure"
    assert row.is_active is True
    db.close()
