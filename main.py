from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine
import models
from sqlalchemy import text

models.Base.metadata.create_all(bind=engine)

def _migrate():
    new_cols = [
        ("discount_amount", "INTEGER DEFAULT 0"),
        ("shipping_fee",    "INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for col, defn in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {defn}"))
                conn.commit()
            except Exception:
                pass

_migrate()

from routers import public, admin

app = FastAPI(title="POLA Shop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)
