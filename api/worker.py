import os,time,uuid
from app.db import Base,engine,SessionLocal
from app.processor import process_job
from app.workflow import ProcessingLease, claim_next_job, finish_job_lease

Base.metadata.create_all(bind=engine)
worker_id=os.getenv('WORKER_ID') or f"worker-{uuid.uuid4().hex[:10]}"
lease_seconds=int(os.getenv('WORKER_LEASE_SECONDS','1800'))
max_attempts=int(os.getenv('WORKER_MAX_ATTEMPTS','3'))
print('PLA QC worker started',worker_id,flush=True)
while True:
    db=SessionLocal()
    try:
        jid=claim_next_job(db,worker_id,lease_seconds,max_attempts)
    finally:
        db.close()
    if jid:
        print('Processing',jid,'as',worker_id,flush=True)
        process_job(jid)
        db=SessionLocal()
        try:
            outcome=finish_job_lease(db,jid,worker_id,max_attempts)
            print('Job',jid,'outcome',outcome,flush=True)
        finally:
            db.close()
    else:
        time.sleep(int(os.getenv('WORKER_POLL_SECONDS','3')))
