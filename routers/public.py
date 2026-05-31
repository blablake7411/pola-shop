from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract
from database import get_db
from models import (Agent, Order, OrderItem, Customer,
                    get_agent_discount, DIRECT_DISCOUNT, YOUR_COST_RATE,
                    calc_tier_by_retail, calc_store_tier_by_retail)
from datetime import datetime, timezone, date
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["public"])

AGENT_PASSWORD = "00000000"


class OrderItemIn(BaseModel):
    product_code: Optional[str] = None
    product_name: str
    product_series: Optional[str] = None
    variant_label: Optional[str] = None
    unit_price: int
    quantity: int


class OrderIn(BaseModel):
    agent_code: Optional[str] = None
    customer_name: str
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None
    items: List[OrderItemIn]


def _gen_order_number(db: Session) -> str:
    today = date.today()
    prefix = today.strftime("%y%m%d")
    count = db.query(func.count(Order.id)).filter(
        Order.order_number.like(f"{prefix}-%")
    ).scalar()
    return f"{prefix}-{count + 1:03d}"


# ── Agent auth ────────────────────────────────────────────────

@router.post("/auth/agent")
def agent_login(body: dict, db: Session = Depends(get_db)):
    phone = (body.get("phone") or "").strip()
    password = body.get("password") or ""
    if password != AGENT_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    agent = db.query(Agent).filter(Agent.phone == phone).first()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _agent_public_dict(agent)


def _agent_public_dict(agent: Agent) -> dict:
    return {
        "code": agent.code,
        "name": agent.name,
        "phone": agent.phone,
        "agent_type": agent.agent_type,
        "current_tier": agent.current_tier,
        "discount_rate": get_agent_discount(agent),
    }


# ── Customer lookup ───────────────────────────────────────────

@router.get("/customers/lookup")
def lookup_customer(phone: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.phone == phone).first()
    if not customer or not customer.agent_code:
        return {"found": False}
    agent = db.query(Agent).filter(Agent.code == customer.agent_code).first()
    if not agent:
        return {"found": False}
    return {"found": True, "agent_code": agent.code, "agent_name": agent.name}


@router.get("/customers/profile")
def customer_profile(phone: str, db: Session = Depends(get_db)):
    orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.customer_phone == phone, Order.status != "已取消")
        .order_by(Order.created_at.desc())
        .all()
    )
    total_retail = sum(o.retail_total for o in orders)
    today = date.today()
    monthly = [o for o in orders if o.created_at and
               o.created_at.year == today.year and o.created_at.month == today.month]
    monthly_retail = sum(o.retail_total for o in monthly)

    # Try to find customer name
    customer = db.query(Customer).filter(Customer.phone == phone).first()
    name = customer.name if customer else None

    return {
        "phone": phone,
        "name": name,
        "total_retail": total_retail,
        "monthly_retail": monthly_retail,
        "order_count": len(orders),
        "orders": [_order_brief(o) for o in orders[:20]],
    }


def _order_brief(o: Order) -> dict:
    return {
        "order_number": o.order_number,
        "status": o.status,
        "retail_total": o.retail_total,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "items": [{"product_name": i.product_name, "quantity": i.quantity, "unit_price": i.unit_price}
                  for i in o.items],
    }


# ── Agents ────────────────────────────────────────────────────

@router.get("/agents/{code}")
def get_agent(code: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.code == code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_public_dict(agent)


@router.get("/agents/{code}/orders")
def get_agent_orders(code: str, month: Optional[str] = None, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.code == code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not month:
        month = date.today().strftime("%Y-%m")
    year, mon = map(int, month.split("-"))

    orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(
            Order.agent_code == code,
            extract("year", Order.created_at) == year,
            extract("month", Order.created_at) == mon,
        )
        .order_by(Order.created_at.desc())
        .all()
    )

    retail_sum = sum(o.retail_total for o in orders if o.status != "已取消")
    return {
        "month": month,
        "retail_sum": retail_sum,
        "order_count": len([o for o in orders if o.status != "已取消"]),
        "items": [_order_dict(o) for o in orders],
    }


@router.get("/agents/{code}/stats")
def get_agent_stats(code: str, db: Session = Depends(get_db)):
    """業務個人頁面所需資料：本月業績、歷年業績、客人清單"""
    agent = db.query(Agent).filter(Agent.code == code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    all_orders = (
        db.query(Order)
        .filter(Order.agent_code == code, Order.status != "已取消")
        .order_by(Order.created_at.desc())
        .all()
    )

    today = date.today()
    monthly = [o for o in all_orders if o.created_at and
               o.created_at.year == today.year and o.created_at.month == today.month]

    total_retail = sum(o.retail_total for o in all_orders)
    monthly_retail = sum(o.retail_total for o in monthly)

    # Unique customers this agent has
    customer_phones = list({o.customer_phone for o in all_orders if o.customer_phone})

    return {
        "agent": _agent_public_dict(agent),
        "total_retail": total_retail,
        "monthly_retail": monthly_retail,
        "total_order_count": len(all_orders),
        "monthly_order_count": len(monthly),
        "customer_count": len(customer_phones),
        "recent_orders": [_order_brief(o) for o in all_orders[:10]],
    }


# ── Orders ────────────────────────────────────────────────────

@router.post("/orders")
def create_order(data: OrderIn, db: Session = Depends(get_db)):
    if not data.items:
        raise HTTPException(status_code=400, detail="Items cannot be empty")

    agent = None

    # 1. agent code from form
    if data.agent_code:
        agent = db.query(Agent).filter(Agent.code == data.agent_code.strip().upper()).first()

    # 2. fallback: phone → customer → agent binding
    if not agent and data.customer_phone:
        customer = db.query(Customer).filter(Customer.phone == data.customer_phone).first()
        if customer and customer.agent_code:
            agent = db.query(Agent).filter(Agent.code == customer.agent_code).first()

    agent_tier = agent.current_tier if agent else None
    agent_discount = get_agent_discount(agent) if agent else DIRECT_DISCOUNT

    retail_total = sum(i.unit_price * i.quantity for i in data.items)
    agent_cost_total = round(retail_total * agent_discount)

    order = Order(
        order_number=_gen_order_number(db),
        agent_code=agent.code if agent else None,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_address=data.customer_address,
        payment_method=data.payment_method,
        notes=data.notes,
        agent_tier=agent_tier,
        agent_discount=agent_discount,
        retail_total=retail_total,
        agent_cost_total=agent_cost_total,
    )
    db.add(order)
    db.flush()

    for item in data.items:
        db.add(OrderItem(
            order_id=order.id,
            product_code=item.product_code,
            product_name=item.product_name,
            product_series=item.product_series,
            variant_label=item.variant_label,
            unit_price=item.unit_price,
            quantity=item.quantity,
        ))

    db.commit()
    db.refresh(order)

    return {
        "order_number": order.order_number,
        "status": order.status,
        "agent_name": agent.name if agent else None,
        "agent_tier": order.agent_tier,
        "agent_discount": order.agent_discount,
        "retail_total": order.retail_total,
        "agent_cost_total": order.agent_cost_total,
        "created_at": order.created_at.isoformat(),
    }


def _order_dict(o: Order) -> dict:
    your_cost = round(o.retail_total * YOUR_COST_RATE)
    return {
        "order_number": o.order_number,
        "agent_code": o.agent_code,
        "customer_name": o.customer_name,
        "customer_phone": o.customer_phone,
        "customer_address": o.customer_address,
        "payment_method": o.payment_method,
        "notes": o.notes,
        "status": o.status,
        "agent_tier": o.agent_tier,
        "agent_discount": o.agent_discount,
        "retail_total": o.retail_total,
        "agent_cost_total": o.agent_cost_total,
        "your_cost": your_cost,
        "your_profit": o.agent_cost_total - your_cost,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
        "shipped_at": o.shipped_at.isoformat() if o.shipped_at else None,
        "items": [
            {
                "product_code": i.product_code,
                "product_name": i.product_name,
                "product_series": i.product_series,
                "variant_label": i.variant_label,
                "unit_price": i.unit_price,
                "quantity": i.quantity,
            }
            for i in o.items
        ],
    }
