import threading
from fastapi import APIRouter, HTTPException, Body

from services.backtest.group_manager import group_manager_instance, group_runner
from services.backtest.task_manager import task_manager

router = APIRouter(prefix="/api/backtest", tags=["strategy-group"])


@router.get("/groups")
def api_list_groups():
    return group_manager_instance.list_groups()


@router.post("/groups")
def api_create_group(body: dict = Body(...)):
    name = body.get("name")
    pipeline = body.get("pipeline", [])
    join_modes = body.get("join_modes", [])
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not pipeline:
        raise HTTPException(status_code=400, detail="pipeline cannot be empty")
    group_id = group_manager_instance.create_group(name, pipeline, join_modes)
    group = group_manager_instance.get_group(group_id)
    return group


@router.post("/groups/migrate")
def api_migrate_groups():
    count = group_manager_instance.migrate_from_tasks(task_manager)
    return {"migrated": count}


@router.get("/groups/{group_id}")
def api_get_group(group_id: str):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.patch("/groups/{group_id}")
def api_update_group(group_id: str, body: dict = Body(...)):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group_manager_instance.update_group(
        group_id,
        name=body.get("name"),
        pipeline=body.get("pipeline"),
        join_modes=body.get("join_modes"),
    )
    return {"ok": True}


@router.delete("/groups/{group_id}")
def api_delete_group(group_id: str):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group_manager_instance.delete_group(group_id)
    return {"ok": True}


@router.post("/groups/{group_id}/run")
def api_run_group(group_id: str, body: dict = Body(...)):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    execution_mode = body.get("execution_mode", "auto")

    if execution_mode == "stepwise":
        run_id = group_runner.run_stepwise_start(group_id, start_date, end_date)
        run = group_manager_instance.get_run(run_id)
        return {"run_id": run_id, "status": run["status"]}
    else:
        run_id = group_manager_instance.create_run(group_id, start_date, end_date, "auto")

        def _do_run():
            group_runner._run_auto_with_run_id(run_id, group_id, start_date, end_date)

        t = threading.Thread(target=_do_run, daemon=True)
        t.start()
        return {"run_id": run_id, "status": "running"}


@router.get("/groups/{group_id}/runs")
def api_list_runs(group_id: str):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group_manager_instance.list_runs(group_id)


@router.get("/runs/{run_id}")
def api_get_run(run_id: str):
    run = group_manager_instance.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/status")
def api_get_run_status(run_id: str):
    run = group_manager_instance.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "status": run["status"], "current_step": run["current_step"]}


@router.post("/runs/{run_id}/next-step")
def api_next_step(run_id: str):
    run = group_manager_instance.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run["status"].startswith("step_") or not run["status"].endswith("_done"):
        raise HTTPException(status_code=400, detail="Run is not waiting for next step")
    group_runner.run_stepwise_next(run_id)
    updated = group_manager_instance.get_run(run_id)
    return {"run_id": run_id, "status": updated["status"], "current_step": updated["current_step"]}
