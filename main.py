from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine
import models
from sqlalchemy import text

models.Base.metadata.create_all(bind=engine)

def _migrate():
    migrations = [
        ("orders",    "discount_amount",  "INTEGER DEFAULT 0"),
        ("orders",    "shipping_fee",     "INTEGER DEFAULT 0"),
        ("customers", "password_hash",    "TEXT"),
        ("customers", "address",          "TEXT"),
        ("customers", "token",            "VARCHAR(64)"),
    ]
    with engine.connect() as conn:
        for table, col, defn in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {defn}"))
                conn.commit()
            except Exception:
                pass

_migrate()

from routers import public, admin, customer

app = FastAPI(title="POLA Shop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(customer.router)
