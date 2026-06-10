from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import Customer, Order, Agent
from datetime import date
import hashlib, os, base64, secrets

router = APIRouter(prefix="/api/customers", tags=["customer-auth"])


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return base64.b64encode(salt + key).decode()


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        data = base64.b64decode(stored_hash.encode())
        salt, stored_key = data[:16], data[16:]
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return secrets.compare_digest(new_key, stored_key)
    except Exception:
        return False


def _by_token(token: str, db: Session):
    if not token:
        return None
    return db.query(Customer).filter(Customer.token == token).first()


def _customer_dict(c: Customer) -> dict:
    return {
        "token": c.token,
        "phone": c.phone,
        "name": c.name,
        "address": c.address or "",
        "agent_code": c.agent_code,
    }


def _order_brief(o: Order) -> dict:
    return {
        "order_number": o.order_number,
        "status": o.status,
        "retail_total": o.retail_total,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "items": [
            {
                "product_name": i.product_name,
                "variant_label": i.variant_label,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
            }
            for i in o.items
        ],
    }


@router.post("/register")
def register_customer(body: dict, db: Session = Depends(get_db)):
    phone = (body.get("phone") or "").strip()
    name = (body.get("name") or "").strip()
    address = (body.get("address") or "").strip()
    agent_code = (body.get("agent_code") or "").strip().upper() or None
    password = body.get("password") or ""

    if not phone or not name or not password:
        raise HTTPException(status_code=400, detail="手機號碼、姓名、密碼為必填")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少 6 位")

    if agent_code:
        agent = db.query(Agent).filter(Agent.code == agent_code).first()
        if not agent:
            raise HTTPException(status_code=400, detail="業務代碼不存在，請確認後重試")

    existing = db.query(Customer).filter(Customer.phone == phone).first()
    if existing and existing.password_hash:
        raise HTTPException(status_code=409, detail="此電話已有帳號，請直接登入")

    new_token = secrets.token_urlsafe(32)

    if existing:
        existing.name = name
        existing.address = address or existing.address
        if agent_code:
            existing.agent_code = agent_code
        existing.password_hash = _hash_password(password)
        existing.token = new_token
        db.commit()
        db.refresh(existing)
        return _customer_dict(existing)

    c = Customer(
        phone=phone,
        name=name,
        address=address or None,
        agent_code=agent_code,
        password_hash=_hash_password(password),
        token=new_token,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _customer_dict(c)


@router.post("/login")
def login_customer(body: dict, db: Session = Depends(get_db)):
    phone = (body.get("phone") or "").strip()
    password = body.get("password") or ""
    if not phone or not password:
        raise HTTPException(status_code=400, detail="請輸入電話和密碼")

    c = db.query(Customer).filter(Customer.phone == phone).first()
    if not c or not c.password_hash:
        raise HTTPException(status_code=401, detail="此電話尚未註冊，請先建立帳號")
    if not _verify_password(password, c.password_hash):
        raise HTTPException(status_code=401, detail="密碼不正確")

    c.token = secrets.token_urlsafe(32)
    db.commit()
    return _customer_dict(c)


@router.get("/me")
def get_me(token: str, db: Session = Depends(get_db)):
    c = _by_token(token, db)
    if not c:
        raise HTTPException(status_code=401, detail="請重新登入")

    orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.customer_phone == c.phone, Order.status != "已取消")
        .order_by(Order.created_at.desc())
        .all()
    )
    today = date.today()
    monthly = [o for o in orders if o.created_at and
               o.created_at.year == today.year and o.created_at.month == today.month]

    data = _customer_dict(c)
    data["monthly_retail"] = sum(o.retail_total for o in monthly)
    data["total_retail"] = sum(o.retail_total for o in orders)
    data["order_count"] = len(orders)
    data["orders"] = [_order_brief(o) for o in orders[:20]]
    return data


@router.patch("/me")
def update_me(body: dict, db: Session = Depends(get_db)):
    c = _by_token(body.get("token") or "", db)
    if not c:
        raise HTTPException(status_code=401, detail="請重新登入")

    if body.get("name"):
        c.name = body["name"].strip()
    if "address" in body:
        c.address = body["address"].strip() or None
    if body.get("new_password"):
        if len(body["new_password"]) < 6:
            raise HTTPException(status_code=400, detail="密碼至少 6 位")
        c.password_hash = _hash_password(body["new_password"])

    db.commit()
    return _customer_dict(c)


@router.post("/logout")
def logout_customer(body: dict, db: Session = Depends(get_db)):
    c = _by_token(body.get("token") or "", db)
    if c:
        c.token = None
        db.commit()
    return {"ok": True}
