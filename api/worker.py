import os,time,uuid,threading
from app.db import SessionLocal,initialize_schema
from app.processor import process_job
from app.workflow import ProcessingLease, claim_next_job, heartbeat_job, finish_job_lease

initialize_schema()
worker_id=os.getenv('WORKER_ID') or f"worker-{uuid.uuid4().hex[:10]}"
lease_seconds=int(os.getenv('WORKER_LEASE_SECONDS','1800'))
heartbeat_seconds=max(10,min(int(os.getenv('WORKER_HEARTBEAT_SECONDS','30')),max(10,lease_seconds//3)))
max_attempts=int(os.getenv('WORKER_MAX_ATTEMPTS','3'))
print('PLA QC worker started',worker_id,flush=True)


def keep_lease_alive(job_id,stop_event):
    while not stop_event.wait(heartbeat_seconds):
        db=SessionLocal()
        try:
            heartbeat_job(db,job_id,worker_id,lease_seconds)
        except Exception as exc:
            db.rollback()
            print('Lease heartbeat warning',job_id,exc,flush=True)
        finally:
            db.close()


while True:
    db=SessionLocal()
    try:
        jid=claim_next_job(db,worker_id,lease_seconds,max_attempts)
    finally:
        db.close()
    if jid:
        print('Processing',jid,'as',worker_id,flush=True)
        stop=threading.Event()
        heartbeat=threading.Thread(target=keep_lease_alive,args=(jid,stop),daemon=True)
        heartbeat.start()
        try:
            process_job(jid)
        finally:
            stop.set()
            heartbeat.join(timeout=heartbeat_seconds+2)
        db=SessionLocal()
        try:
            outcome=finish_job_lease(db,jid,worker_id,max_attempts)
            print('Job',jid,'outcome',outcome,flush=True)
        finally:
            db.close()
    else:
        time.sleep(int(os.getenv('WORKER_POLL_SECONDS','3')))
