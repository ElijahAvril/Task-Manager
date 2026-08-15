from fastapi import Depends, FastAPI, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db, Base, engine
from models import TaskDB, UserDB
from pydantic import BaseModel, Field
from typing import Optional
from auth import hash_password, verify_password, create_access_token, get_current_user
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from logging_config import logger
from cache import redis_client
import json 



Base.metadata.create_all(bind=engine)

class TaskCreate(BaseModel):
    title: str
    description: str

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

class UserCreate(BaseModel):
    username: str
    password: str = Field(..., max_length=72)

class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True

app = FastAPI()



@app.get("/tasks")
def read_tasks(db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    cache_key = f"tasks:{current_user.id}"
    
    cached = redis_client.get(cache_key)  # step 1: check Redis for this key
    if cached:
        return json.loads(cached)  # step 2: what do you need to do to the cached value before returning it?
    
    tasks = db.query(TaskDB).filter(TaskDB.owner_id == current_user.id).all()
    
    task_list = [{"id": t.id, "title": t.title, "description": t.description} for t in tasks]
    redis_client.set(cache_key, json.dumps(task_list))  # step 3: store the result in Redis before returning
    
    return tasks

@app.get("/tasks/{task_id}")
def read_task(db: Session = Depends(get_db), task_id: int = None, current_user: UserDB = Depends(get_current_user)):
    task = db.query(TaskDB).filter(TaskDB.owner_id == current_user.id).filter(TaskDB.id == task_id).first()
    if task:
        return task
    raise HTTPException(status_code=404, detail="Task not found")

@app.get("/")
def read_root():
    return {"message": "Task Manager API is running"}

@app.post("/tasks")
def create_task(task: TaskCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    cache_key = f"tasks:{current_user.id}"
    new_task = TaskDB(owner_id = current_user.id, title=task.title, description=task.description)
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    redis_client.delete(cache_key)
    return new_task

@app.delete("/tasks/{task_id}", status_code = status.HTTP_204_NO_CONTENT)
def delete_task(db: Session = Depends(get_db), task_id: int = None, current_user: UserDB = Depends(get_current_user)):
    cache_key = f"tasks:{current_user.id}"
    deltask = db.query(TaskDB).filter(TaskDB.owner_id == current_user.id).filter(TaskDB.id == task_id).first()
    if deltask:
        db.delete(deltask)
        db.commit()
        redis_client.delete(cache_key)
        return
    raise HTTPException(status_code=404, detail="Task not found")

@app.put("/tasks/{task_id}")
def put_task(task: TaskCreate, db: Session = Depends(get_db), task_id:int= None, current_user: UserDB = Depends(get_current_user)):
    cache_key = f"tasks:{current_user.id}"
    oldtask = db.query(TaskDB).filter(TaskDB.owner_id == current_user.id).filter(TaskDB.id == task_id).first()
    if oldtask:
        oldtask.title = task.title
        oldtask.description = task.description
        db.commit()
        db.refresh(oldtask)
        redis_client.delete(cache_key)
        return oldtask
    else:
        raise HTTPException(status_code=404, detail="Task not found")

@app.patch("/tasks/{task_id}")
def patch_task(task: TaskUpdate, db: Session = Depends(get_db), task_id: int = None, current_user: UserDB = Depends(get_current_user)):
    cache_key = f"tasks:{current_user.id}"
    oldtask = db.query(TaskDB).filter(TaskDB.owner_id == current_user.id).filter(TaskDB.id == task_id).first()
    newtask = task.model_dump(exclude_unset=True)
    if oldtask:
        if newtask.get("title"):
            oldtask.title = newtask.get("title")
        if newtask.get("description"):
            oldtask.description = newtask.get("description")
        db.commit()
        db.refresh(oldtask)
        redis_client.delete(cache_key)
        return oldtask
    else:
        raise HTTPException(status_code=404, detail="Task not found")

@app.post("/register", response_model= UserOut)
def register_user(user: UserCreate, db: Session = Depends(get_db), ):
    usersname = db.query(UserDB).filter(UserDB.username == user.username).first()
    if usersname:
        raise HTTPException(status_code=409, detail="Username already exists")
    else: 
        newuser = UserDB(username = user.username, hashed_password = hash_password(user.password))
        logger.info(f"User {user.username} registered successfully")
        db.add(newuser)
        db.commit()
        db.refresh(newuser)
        return newuser

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username==form_data.username).first()  # step 1
    
    if not user or not verify_password(form_data.password, user.hashed_password):  # step 2
        logger.warning(f"Failed login attempt for username: {form_data.username}")
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token({"sub": form_data.username})  # step 3
    logger.info(f"User {form_data.username} logged in successfully")
    return {"access_token": access_token, "token_type": "bearer"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again later."}
    )

