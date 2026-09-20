"""
Task Manager - نظام إدارة المهام الكامل
كل شيء في ملف واحد: قاعدة البيانات + Workflow + API + واجهة
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from datetime import datetime, timedelta
from typing import Optional

# ============================================================
# 1. قاعدة البيانات (SQLite)
# ============================================================
DATABASE_URL = "sqlite:///./tasks.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================
# 2. نموذج المهمة
# ============================================================
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


# ============================================================
# 3. منطق سير العمل (Workflow)
# ============================================================
SLA_HOURS = {"CRITICAL": 2, "HIGH": 8, "MEDIUM": 24, "LOW": 72}
ALERT_MESSAGES = {
    "CRITICAL": "🚨 URGENT ALERT",
    "HIGH": "⚠️ PRIORITY ALERT",
    "MEDIUM": "📌 STANDARD NOTICE",
    "LOW": "📥 ACKNOWLEDGE TASK",
}


def log(task: Task, event: str):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    task.activity_log = (task.activity_log or "") + f"[{timestamp}] {event}\n"


def validate_task(task: Task) -> bool:
    if not task.title or len(task.title.strip()) < 3:
        return False
    if task.priority not in SLA_HOURS:
        return False
    log(task, "✅ Validation passed")
    return True


def priority_router(task: Task):
    log(task, f"🔀 Priority Router → {ALERT_MESSAGES.get(task.priority, 'NOTICE')}")


def calculate_sla(task: Task):
    hours = SLA_HOURS.get(task.priority, 24)
    task.due_date = datetime.utcnow() + timedelta(hours=hours)
    log(task, f"⏱️ SLA: {hours}h | Due: {task.due_date.strftime('%Y-%m-%d %H:%M')}")


def assign_department(task: Task, department: str):
    task.department = department or "General"
    log(task, f"🏢 Department → {task.department}")


def assign_person(task: Task, person: str):
    task.assignee = person or "Me"
    task.status = "ASSIGNED"
    log(task, f"👤 Assigned to {task.assignee} | Status → ASSIGNED")


def start_progress(task: Task):
    task.status = "IN_PROGRESS"
    log(task, "▶️ Status → IN_PROGRESS")


def monitor_sla(task: Task) -> bool:
    if task.due_date and datetime.utcnow() > task.due_date:
        task.status = "ESCALATED"
        log(task, "⚠️ OVERDUE → ESCALATED")
        return False
    log(task, "✅ ON TIME → CONTINUE")
    return True


def complete_task(task: Task):
    task.status = "CLOSED"
    task.closed_at = datetime.utcnow()
    log(task, "✔️ COMPLETED → CLOSED")


# ============================================================
# 4. FastAPI App
# ============================================================
app = FastAPI(title="Task Manager")


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    task_type: Optional[str] = "GENERAL"
    priority: str = "MEDIUM"
    department: Optional[str] = "General"
    assignee: Optional[str] = "Me"


def task_to_dict(t: Task):
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
    log(task, f"📥 Task created: {task.title}")

    if not validate_task(task):
        raise HTTPException(status_code=400, detail="Invalid task data")

    log(task, f"🔍 Type: {task.task_type} | Priority: {task.priority}")
    priority_router(task)
    calculate_sla(task)
    assign_department(task, payload.department)
    assign_person(task, payload.assignee)
    log(task, f"🔔 Reminder sent to {task.assignee}")
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


# ============================================================
# 5. الواجهة العربية
# ============================================================
@app.get("/ui", response_class=HTMLResponse)
def ui():
    return """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مدير المهام</title>
<style>

\\\&#x20; \\\\\\\* { box-sizing: border-box; }

\\\&#x20; body { font-family: 'Segoe UI', Tahoma, Arial; background: #f0f2f5; padding: 20px; margin: 0; }

\\\&#x20; .container { max-width: 900px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }

\\\&#x20; h1 { color: #1a1a2e; margin-top: 0; }

\\\&#x20; .form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }

\\\&#x20; input, select { padding: 12px; border-radius: 8px; border: 1px solid #ddd; font-size: 14px; }

\\\&#x20; input#title { flex: 1; min-width: 200px; }

\\\&#x20; button { padding: 12px 20px; background: #007bff; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: bold; }

\\\&#x20; button:hover { background: #0056b3; }

\\\&#x20; button.danger { background: #dc3545; }

\\\&#x20; button.danger:hover { background: #a02030; }

\\\&#x20; button.success { background: #28a745; }

\\\&#x20; button.success:hover { background: #1e7e34; }

\\\&#x20; .task { border-right: 5px solid #007bff; padding: 15px; margin: 12px 0; background: #f9f9f9; border-radius: 8px; }

\\\&#x20; .task.CRITICAL { border-color: #dc3545; background: #fff5f5; }

\\\&#x20; .task.HIGH { border-color: #fd7e14; background: #fff8f0; }

\\\&#x20; .task.MEDIUM { border-color: #ffc107; background: #fffdf0; }

\\\&#x20; .task.LOW { border-color: #28a745; background: #f0fff4; }

\\\&#x20; .task.CLOSED { opacity: 0.6; }

\\\&#x20; .badge { font-size: 11px; padding: 3px 10px; border-radius: 12px; background: #e0e0e0; margin-left: 5px; font-weight: bold; }

\\\&#x20; .badge.NEW { background: #cfe2ff; color: #084298; }

\\\&#x20; .badge.ASSIGNED { background: #fff3cd; color: #664d03; }

\\\&#x20; .badge.IN\\\\\\\_PROGRESS { background: #cff4fc; color: #055160; }

\\\&#x20; .badge.ESCALATED { background: #f8d7da; color: #842029; }

\\\&#x20; .badge.CLOSED { background: #d1e7dd; color: #0f5132; }

\\\&#x20; .meta { font-size: 13px; color: #666; margin: 8px 0; }

\\\&#x20; pre { background: #eee; padding: 10px; font-size: 11px; overflow-x: auto; border-radius: 5px; direction: ltr; text-align: left; }

\\\&#x20; .actions { margin-top: 10px; display: flex; gap: 8px; }

\\\&#x20; .empty { text-align: center; color: #999; padding: 40px; }


</head>

<body>

<div class="container">

\&#x20; <h1>📋 مدير المهام</h1>

\&#x20; <div class="form-row">

\&#x20;   <input id="title" placeholder="اكتب عنوان المهمة..." onkeypress="if(event.key==='Enter')addTask()">

\&#x20;   <select id="priority">

\&#x20;     <option value="LOW">🟢 منخفضة (72 ساعة)</option>

\&#x20;     <option value="MEDIUM" selected>🟡 متوسطة (24 ساعة)</option>

\&#x20;     <option value="HIGH">🟠 عالية (8 ساعات)</option>

\&#x20;     <option value="CRITICAL">🔴 حرجة (ساعتان)</option>

\&#x20;   </select>

\&#x20;   <button onclick="addTask()">➕ إضافة</button>

\&#x20; </div>

\&#x20; <div id="tasks"><div class="empty">جاري التحميل...</div></div>

</div>



<script>

async function load() {

\\\&#x20; try {

\\\&#x20;   const r = await fetch('/tasks');

\\\&#x20;   const data = await r.json();

\\\&#x20;   const el = document.getElementById('tasks');

\\\&#x20;   if (data.length === 0) {

\\\&#x20;     el.innerHTML = '<div class="empty">لا توجد مهام بعد. أضف مهمتك الأولى! ✨</div>';

\\\&#x20;     return;

\\\&#x20;   }

\\\&#x20;   el.innerHTML = data.map(t => `

\\\&#x20;     <div class="task ${t.priority} ${t.status}">

\\\&#x20;       <div>

\\\&#x20;         <b>#${t.id} — ${t.title}</b>

\\\&#x20;         <span class="badge ${t.status}">${t.status}</span>

\\\&#x20;         <span class="badge">${t.priority}</span>

\\\&#x20;       </div>

\\\&#x20;       <div class="meta">👤 ${t.assignee} \\\\\\\&nbsp;|\\\\\\\&nbsp; 🏢 ${t.department}</div>

\\\&#x20;       <div class="meta">⏱️ الموعد النهائي: ${t.due\\\\\\\_date ? new Date(t.due\\\\\\\_date).toLocaleString('ar') : '-'}</div>


\&#x20;       <div class="actions">

\&#x20;         ${t.status !== 'CLOSED' ? `<button class="success" onclick="completeTask(${t.id})">✔️ إكمال</button>` : ''}

\&#x20;         <button class="danger" onclick="deleteTask(${t.id})">🗑️ حذف</button>

\&#x20;       </div>

\&#x20;     </div>

\&#x20;   `).join('');

\&#x20; } catch(e) {

\&#x20;   document.getElementById('tasks').innerHTML = '<div class="empty">❌ خطأ في التحميل</div>';

\&#x20; }

}



async function addTask() {

\&#x20; const title = document.getElementById('title').value.trim();

\&#x20; if (!title) return alert('اكتب عنوان المهمة');

\&#x20; await fetch('/tasks', {

\&#x20;   method: 'POST',

\&#x20;   headers: {'Content-Type': 'application/json'},

\&#x20;   body: JSON.stringify({ title, priority: document.getElementById('priority').value })

\&#x20; });

\&#x20; document.getElementById('title').value = '';

\&#x20; load();

}



async function completeTask(id) {

\&#x20; await fetch(`/tasks/${id}/complete`, { method: 'POST' });

\&#x20; load();

}



async function deleteTask(id) {

\&#x20; if (!confirm('هل تريد حذف المهمة؟')) return;

\&#x20; await fetch(`/tasks/${id}`, { method: 'DELETE' });

\&#x20; load();

}



load();


</body>

</html>

"""
