from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract
from database import get_db
from models import Agent, Order, OrderItem, Customer, get_discount, YOUR_COST_RATE
from datetime import datetime, timezone, date
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["public"])


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


@router.get("/customers/lookup")
def lookup_customer(phone: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.phone == phone).first()
    if not customer or not customer.agent_code:
        return {"found": False}
    agent = db.query(Agent).filter(Agent.code == customer.agent_code).first()
    if not agent:
        return {"found": False}
    return {"found": True, "agent_code": agent.code, "agent_name": agent.name}


@router.get("/agents/{code}")
def get_agent(code: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.code == code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "code": agent.code,
        "name": agent.name,
        "phone": agent.phone,
        "current_tier": agent.current_tier,
        "discount_rate": get_discount(agent.current_tier),
        "joined_at": agent.joined_at,
        "manual_override": agent.manual_override,
    }


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
    return {"month": month, "items": [_order_dict(o) for o in orders]}


@router.post("/orders")
def create_order(data: OrderIn, db: Session = Depends(get_db)):
    if not data.items:
        raise HTTPException(status_code=400, detail="Items cannot be empty")

    agent = None
    agent_tier = None
    agent_discount = None

    if data.agent_code:
        agent = db.query(Agent).filter(Agent.code == data.agent_code).first()
    elif data.customer_phone:
        customer = db.query(Customer).filter(Customer.phone == data.customer_phone).first()
        if customer and customer.agent_code:
            agent = db.query(Agent).filter(Agent.code == customer.agent_code).first()

    if agent:
        agent_tier = agent.current_tier
        agent_discount = get_discount(agent_tier)

    retail_total = sum(i.unit_price * i.quantity for i in data.items)
    agent_cost_total = round(retail_total * agent_discount) if agent_discount else retail_total

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
