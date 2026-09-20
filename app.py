"""
Task Manager - نظام إدارة المهام
ملف واحد فيه كل شيء: قاعدة بيانات + workflow + API + واجهة
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from datetime import datetime, timedelta
from typing import Optional

# ============ قاعدة البيانات ============
DATABASE_URL = "sqlite:///./tasks.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    task_type = Column(String(50), default="GENERAL")
    priority = Column(String(20), default="MEDIUM")
    status = Column(String(30), default="NEW")
    department = Column(String(100), default="")
    assignee = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    activity_log = Column(Text, default="")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============ Workflow ============
SLA_HOURS = {"CRITICAL": 2, "HIGH": 8, "MEDIUM": 24, "LOW": 72}
ALERT_MESSAGES = {
    "CRITICAL": "URGENT ALERT",
    "HIGH": "PRIORITY ALERT",
    "MEDIUM": "STANDARD NOTICE",
    "LOW": "ACKNOWLEDGE TASK",
}


def log(task, event):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    task.activity_log = (task.activity_log or "") + "[{}] {}\n".format(ts, event)


def validate_task(task):
    if not task.title or len(task.title.strip()) < 3:
        return False
    if task.priority not in SLA_HOURS:
        return False
    log(task, "Validation passed")
    return True


def priority_router(task):
    msg = ALERT_MESSAGES.get(task.priority, "NOTICE")
    log(task, "Priority Router -> " + msg)


def calculate_sla(task):
    hours = SLA_HOURS.get(task.priority, 24)
    task.due_date = datetime.utcnow() + timedelta(hours=hours)
    log(task, "SLA: {}h | Due: {}".format(hours, task.due_date.strftime("%Y-%m-%d %H:%M")))


def assign_department(task, department):
    task.department = department or "General"
    log(task, "Department -> " + task.department)


def assign_person(task, person):
    task.assignee = person or "Me"
    task.status = "ASSIGNED"
    log(task, "Assigned to " + task.assignee + " | Status -> ASSIGNED")


def start_progress(task):
    task.status = "IN_PROGRESS"
    log(task, "Status -> IN_PROGRESS")


def monitor_sla(task):
    if task.due_date and datetime.utcnow() > task.due_date:
        task.status = "ESCALATED"
        log(task, "OVERDUE -> ESCALATED")
        return False
    log(task, "ON TIME -> CONTINUE")
    return True


def complete_task(task):
    task.status = "CLOSED"
    task.closed_at = datetime.utcnow()
    log(task, "COMPLETED -> CLOSED")


# ============ API ============
app = FastAPI(title="Task Manager")


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    task_type: Optional[str] = "GENERAL"
    priority: str = "MEDIUM"
    department: Optional[str] = "General"
    assignee: Optional[str] = "Me"


def task_to_dict(t):
    return {
        "id": t.id,
        "title": t.title,
        "priority": t.priority,
        "status": t.status,
        "department": t.department,
        "assignee": t.assignee,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "activity_log": t.activity_log,
    }


@app.get("/")
def root():
    return {"status": "alive", "service": "Task Manager", "time": datetime.utcnow().isoformat()}


@app.post("/tasks")
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = Task(
        title=payload.title,
        description=payload.description,
        task_type=payload.task_type,
        priority=payload.priority.upper(),
        status="NEW",
        activity_log="",
    )
    log(task, "Task created: " + task.title)
    if not validate_task(task):
        raise HTTPException(status_code=400, detail="Invalid task data")
    log(task, "Type: {} | Priority: {}".format(task.task_type, task.priority))
    priority_router(task)
    calculate_sla(task)
    assign_department(task, payload.department)
    assign_person(task, payload.assignee)
    log(task, "Reminder sent to " + task.assignee)
    start_progress(task)
    monitor_sla(task)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task_to_dict(task)


@app.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    return [task_to_dict(t) for t in tasks]


@app.post("/tasks/{task_id}/complete")
def complete(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    complete_task(task)
    db.commit()
    db.refresh(task)
    return task_to_dict(task)


@app.delete("/tasks/{task_id}")
def delete(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"deleted": task_id}


# ============ واجهة المستخدم ============
@app.get("/ui", response_class=HTMLResponse)
def ui():
    return """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مدير المهام</title>
<style>
body { font-family: Tahoma, Arial; background: #f0f2f5; padding: 20px; margin: 0; }
.container { max-width: 900px; margin: auto; background: white; padding: 25px; border-radius: 12px; }
h1 { color: #1a1a2e; }
.form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
input, select { padding: 12px; border-radius: 8px; border: 1px solid #ddd; font-size: 14px; }
input#title { flex: 1; min-width: 200px; }
button { padding: 12px 20px; background: #007bff; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; }
button:hover { background: #0056b3; }
button.danger { background: #dc3545; }
button.success { background: #28a745; }
.task { border-right: 5px solid #007bff; padding: 15px; margin: 12px 0; background: #f9f9f9; border-radius: 8px; }
.task.CRITICAL { border-color: #dc3545; background: #fff5f5; }
.task.HIGH { border-color: #fd7e14; }
.task.MEDIUM { border-color: #ffc107; }
.task.LOW { border-color: #28a745; }
.task.CLOSED { opacity: 0.6; }
.badge { font-size: 11px; padding: 3px 10px; border-radius: 12px; background: #e0e0e0; margin-left: 5px; font-weight: bold; }
.badge.NEW { background: #cfe2ff; }
.badge.ASSIGNED { background: #fff3cd; }
.badge.IN_PROGRESS { background: #cff4fc; }
.badge.ESCALATED { background: #f8d7da; }
.badge.CLOSED { background: #d1e7dd; }
.meta { font-size: 13px; color: #666; margin: 8px 0; }
pre { background: #eee; padding: 10px; font-size: 11px; overflow-x: auto; border-radius: 5px; direction: ltr; text-align: left; }
.actions { margin-top: 10px; display: flex; gap: 8px; }
.empty { text-align: center; color: #999; padding: 40px; }
</style>
</head>
<body>
<div class="container">
<h1>مدير المهام</h1>
<div class="form-row">
<input id="title" placeholder="اكتب عنوان المهمة..." onkeypress="if(event.key==='Enter')addTask()">
<select id="priority">
<option value="LOW">منخفضة (72 ساعة)</option>
<option value="MEDIUM" selected>متوسطة (24 ساعة)</option>
<option value="HIGH">عالية (8 ساعات)</option>
<option value="CRITICAL">حرجة (ساعتان)</option>
</select>
<button onclick="addTask()">اضافة</button>
</div>
<div id="tasks"><div class="empty">جاري التحميل...</div></div>
</div>
<script>
async function load() {
  try {
    var r = await fetch('/tasks');
    var data = await r.json();
    var el = document.getElementById('tasks');
    if (data.length === 0) {
      el.innerHTML = '<div class="empty">لا توجد مهام بعد</div>';
      return;
    }
    el.innerHTML = data.map(function(t) {
      return '<div class="task ' + t.priority + ' ' + t.status + '">' +
        '<div><b>#' + t.id + ' - ' + t.title + '</b>' +
        '<span class="badge ' + t.status + '">' + t.status + '</span>' +
        '<span class="badge">' + t.priority + '</span></div>' +
        '<div class="meta">' + t.assignee + ' | ' + t.department + '</div>' +
        '<div class="meta">الموعد: ' + (t.due_date || '-') + '</div>' +
        '<details><summary>سجل النشاط</summary><pre>' + (t.activity_log || '') + '</pre></details>' +
        '<div class="actions">' +
        (t.status !== 'CLOSED' ? '<button class="success" onclick="completeTask(' + t.id + ')">اكمال</button>' : '') +
        '<button class="danger" onclick="deleteTask(' + t.id + ')">حذف</button>' +
        '</div></div>';
    }).join('');
  } catch(e) {
    document.getElementById('tasks').innerHTML = '<div class="empty">خطأ في التحميل</div>';
  }
}
async function addTask() {
  var title = document.getElementById('title').value.trim();
  if (!title) { alert('اكتب عنوان المهمة'); return; }
  await fetch('/tasks', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ title: title, priority: document.getElementById('priority').value })
  });
  document.getElementById('title').value = '';
  load();
}
async function completeTask(id) {
  await fetch('/tasks/' + id + '/complete', { method: 'POST' });
  load();
}
async function deleteTask(id) {
  if (!confirm('حذف المهمة؟')) return;
  await fetch('/tasks/' + id, { method: 'DELETE' });
  load();
}
load();
</script>
</body>
</html>"""
