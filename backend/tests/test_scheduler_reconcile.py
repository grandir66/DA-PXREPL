"""Test fix import reconcile nello scheduler."""

import pytest


@pytest.mark.asyncio
async def test_scheduler_reconcile_imports_resolve():
    """Verifica che gli import periodici reconcile non falliscano."""
    from services.scheduler import SchedulerService

    sched = SchedulerService()
    # Non deve sollevare ImportError (bug _reconcile_pending_vm_registrations)
    await sched._reconcile_stuck_sync_jobs()
