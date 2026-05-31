from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import Order, OrderItem, Agent
from schemas import OrderCreate, OrderUpdate, OrderOut
from typing import List, Optional
from datetime import datetime, timezone

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _next_order_number(db: Session) -> str:
    count = db.query(Order).count()
    return f"POLA-{count + 1:05d}"


def _load_order(db: Session, order_id: int) -> Order:
    order = (
        db.query(Order)
        .options(joinedload(Order.agent), joinedload(Order.items))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/", response_model=List[OrderOut])
def list_orders(
    status: Optional[str] = None,
    payment_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Order).options(joinedload(Order.agent), joinedload(Order.items))
    if status:
        q = q.filter(Order.status == status)
    if payment_status:
        q = q.filter(Order.payment_status == payment_status)
    return q.order_by(Order.created_at.desc()).all()


@router.post("/", response_model=OrderOut)
def create_order(data: OrderCreate, db: Session = Depends(get_db)):
    agent = None
    discount_rate = 1.0
    if data.agent_code:
        agent = db.query(Agent).filter(Agent.code == data.agent_code).first()
        if agent:
            discount_rate = agent.discount_rate

    subtotal = sum(item.unit_price * item.quantity for item in data.items)
    discount_amount = round(subtotal * (1 - discount_rate))
    final_amount = subtotal - discount_amount + data.shipping_fee

    order = Order(
        order_number=_next_order_number(db),
        agent_id=agent.id if agent else None,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_address=data.customer_address,
        payment_method=data.payment_method,
        shipping_fee=data.shipping_fee,
        subtotal=subtotal,
        discount_amount=discount_amount,
        final_amount=final_amount,
        notes=data.notes,
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
            item_subtotal=item.unit_price * item.quantity,
        ))

    db.commit()
    return _load_order(db, order.id)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return _load_order(db, order_id)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(order_id: int, data: OrderUpdate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(order, field, value)
    order.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _load_order(db, order_id)


@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(order)
    db.commit()
    return {"ok": True}
