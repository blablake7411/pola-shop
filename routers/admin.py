from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract
from database import get_db
from models import (Agent, Order, OrderItem, Customer, GiftRequest,
                    get_discount, get_store_discount, get_agent_discount,
                    YOUR_COST_RATE, TIERS, STORE_TIERS, DIRECT_DISCOUNT,
                    calc_tier_by_retail, calc_store_tier_by_retail, now_utc)
from datetime import datetime, timezone, date
from typing import Optional
import os

from routers.public import _order_dict, _gift_request_dict

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "pola-admin-2026")


def _auth(authorization: Optional[str] = Header(None)):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _agent_monthly_stats(agent_code: str, month: str, db: Session) -> dict:
    year, mon = map(int, month.split("-"))
    orders = (
        db.query(Order)
        .filter(
            Order.agent_code == agent_code,
            Order.status != "已取消",
            extract("year", Order.created_at) == year,
            extract("month", Order.created_at) == mon,
        )
        .all()
    )
    retail_sum = sum(o.retail_total for o in orders)
    agent_cost_sum = sum(o.agent_cost_total for o in orders)
    your_cost = round(retail_sum * YOUR_COST_RATE)
    return {
        "month": month,
        "retail_sum": retail_sum,
        "order_count": len(orders),
        "agent_cost_sum": agent_cost_sum,
        "your_profit_sum": agent_cost_sum - your_cost,
        "calculated_tier_next_month": calc_tier_by_retail(retail_sum),
    }


def _agent_gift_stats(agent_code: str, month: str, db: Session) -> dict:
    year, mon = map(int, month.split("-"))
    reqs = db.query(GiftRequest).filter(
        GiftRequest.agent_code == agent_code,
        GiftRequest.status != "已取消",
        extract("year", GiftRequest.created_at) == year,
        extract("month", GiftRequest.created_at) == mon,
    ).all()
    return {
        "gift_total_sum": sum(r.gift_total for r in reqs),
        "gift_request_count": len(reqs),
    }


def _agent_dict(a: Agent, month: str, db: Session) -> dict:
    stats = _agent_monthly_stats(a.code, month, db)
    gift_stats = _agent_gift_stats(a.code, month, db)
    return {
        "code": a.code,
        "name": a.name,
        "phone": a.phone,
        "agent_type": getattr(a, "agent_type", "personal"),
        "current_tier": a.current_tier,
        "discount_rate": get_agent_discount(a),
        "manual_override": a.manual_override,
        "joined_at": a.joined_at,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "monthly_stats": {**stats, **gift_stats},
    }


@router.get("/orders")
def list_orders(
    month: Optional[str] = None,
    status: Optional[str] = None,
    agent_code: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    if not month:
        month = date.today().strftime("%Y-%m")
    year, mon = map(int, month.split("-"))

    query = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(
            extract("year", Order.created_at) == year,
            extract("month", Order.created_at) == mon,
        )
        .order_by(Order.created_at.desc())
    )
    if status:
        query = query.filter(Order.status == status)
    if agent_code:
        query = query.filter(Order.agent_code == agent_code)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Order.order_number.ilike(like))
            | (Order.customer_name.ilike(like))
            | (Order.customer_phone.ilike(like))
        )

    orders = query.all()
    return {"month": month, "total": len(orders), "items": [_order_dict(o) for o in orders]}


@router.patch("/orders/{order_number}/status")
def update_order_status(
    order_number: str,
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    order = db.query(Order).filter(Order.order_number == order_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status required")

    now = now_utc()
    order.status = new_status
    if new_status == "已確認" and not order.confirmed_at:
        order.confirmed_at = now
    elif new_status == "已出貨" and not order.shipped_at:
        order.shipped_at = now

    db.commit()
    db.refresh(order)
    return _order_dict(order)


@router.patch("/orders/{order_number}/customer")
def update_order_customer(
    order_number: str,
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    order = db.query(Order).filter(Order.order_number == order_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    for field in ["customer_name", "customer_phone", "customer_address", "notes", "payment_method"]:
        if field in body:
            setattr(order, field, body[field] or None)
    db.commit()
    db.refresh(order)
    return _order_dict(order)


@router.patch("/orders/{order_number}")
def update_order_full(
    order_number: str,
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    order = db.query(Order).filter(Order.order_number == order_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    for field in ["customer_name", "customer_phone", "customer_address", "notes", "payment_method"]:
        if field in body:
            setattr(order, field, body[field] or None)

    if "agent_code" in body:
        agent_code = body["agent_code"] or None
        order.agent_code = agent_code
        if agent_code:
            agent = db.query(Agent).filter(Agent.code == agent_code).first()
            if agent:
                order.agent_tier = agent.current_tier
                order.agent_discount = get_agent_discount(agent)
            else:
                order.agent_tier = None
                order.agent_discount = DIRECT_DISCOUNT
        else:
            order.agent_tier = None
            order.agent_discount = DIRECT_DISCOUNT

    if "items" in body:
        for item in list(order.items):
            db.delete(item)
        db.flush()

        items_data = body["items"]
        for item_data in items_data:
            db.add(OrderItem(
                order_id=order.id,
                product_code=item_data.get("product_code"),
                product_name=item_data["product_name"],
                product_series=item_data.get("product_series"),
                variant_label=item_data.get("variant_label"),
                unit_price=int(item_data["unit_price"]),
                quantity=int(item_data.get("quantity", 1)),
            ))
        db.flush()
        db.refresh(order)

        retail_total = sum(i.unit_price * i.quantity for i in order.items)
        order.retail_total = retail_total
        discount = order.agent_discount or DIRECT_DISCOUNT
        order.agent_cost_total = round(retail_total * discount)

    db.commit()
    db.refresh(order)
    return _order_dict(order)



@router.get("/agents")
def list_agents(
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    if not month:
        month = date.today().strftime("%Y-%m")
    agents = db.query(Agent).order_by(Agent.created_at).all()
    return [_agent_dict(a, month, db) for a in agents]


@router.post("/agents")
def create_agent(
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="code and name required")
    if db.query(Agent).filter(Agent.code == code).first():
        raise HTTPException(status_code=400, detail="Code already exists")

    agent = Agent(
        code=code,
        name=name,
        phone=body.get("phone"),
        agent_type=body.get("agent_type", "personal"),
        current_tier=body.get("current_tier", 1),
        manual_override=body.get("manual_override", False),
        joined_at=body.get("joined_at") or date.today().isoformat(),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _agent_dict(agent, date.today().strftime("%Y-%m"), db)


@router.patch("/agents/{code}")
def update_agent(
    code: str,
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    agent = db.query(Agent).filter(Agent.code == code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    for field in ["name", "phone", "agent_type", "current_tier", "manual_override", "joined_at"]:
        if field in body:
            setattr(agent, field, body[field])

    db.commit()
    return _agent_dict(agent, date.today().strftime("%Y-%m"), db)


@router.delete("/agents/{code}")
def delete_agent(
    code: str,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    agent = db.query(Agent).filter(Agent.code == code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    db.query(Order).filter(Order.agent_code == code).update({"agent_code": None})
    db.delete(agent)
    db.commit()
    return {"ok": True}


@router.get("/dashboard/kpi")
def get_kpi(
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    if not month:
        month = date.today().strftime("%Y-%m")
    year, mon = map(int, month.split("-"))

    all_orders = db.query(Order).filter(
        extract("year", Order.created_at) == year,
        extract("month", Order.created_at) == mon,
    ).all()

    valid = [o for o in all_orders if o.status != "已取消"]
    retail_total = sum(o.retail_total for o in valid)
    agent_cost_total = sum(o.agent_cost_total for o in valid)
    your_cost_total = round(retail_total * YOUR_COST_RATE)

    return {
        "month": month,
        "order_count": len(valid),
        "cancelled_count": len(all_orders) - len(valid),
        "retail_total": retail_total,
        "agent_cost_total": agent_cost_total,
        "your_cost_total": your_cost_total,
        "your_profit": agent_cost_total - your_cost_total,
        "pending_count": sum(1 for o in all_orders if o.status == "待確認"),
    }


@router.get("/reports/monthly")
def get_monthly_report(
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    if not month:
        month = date.today().strftime("%Y-%m")
    year, mon = map(int, month.split("-"))

    all_orders = db.query(Order).filter(
        extract("year", Order.created_at) == year,
        extract("month", Order.created_at) == mon,
    ).all()

    valid = [o for o in all_orders if o.status != "已取消"]
    retail_total = sum(o.retail_total for o in valid)
    agent_cost_total = sum(o.agent_cost_total for o in valid)
    your_cost_total = round(retail_total * YOUR_COST_RATE)

    agents = db.query(Agent).all()
    agent_ranking = []
    for a in agents:
        stats = _agent_monthly_stats(a.code, month, db)
        if stats["retail_sum"] > 0:
            agent_ranking.append({
                "code": a.code,
                "name": a.name,
                "retail_sum": stats["retail_sum"],
            })
    agent_ranking.sort(key=lambda x: -x["retail_sum"])

    return {
        "month": month,
        "summary": {
            "order_count": len(valid),
            "cancelled_count": len(all_orders) - len(valid),
            "retail_total": retail_total,
            "agent_cost_total": agent_cost_total,
            "your_cost_total": your_cost_total,
            "your_profit": agent_cost_total - your_cost_total,
        },
        "agent_ranking": agent_ranking,
    }


# ── Customers ─────────────────────────────────────────────────

@router.get("/customers")
def list_customers(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    customers = db.query(Customer).order_by(Customer.created_at).all()
    return [
        {
            "id": c.id,
            "phone": c.phone,
            "name": c.name,
            "agent_code": c.agent_code,
            "agent_name": c.agent.name if c.agent else None,
            "notes": c.notes,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in customers
    ]


@router.post("/customers")
def create_customer(
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    phone = (body.get("phone") or "").strip()
    name = (body.get("name") or "").strip()
    if not phone or not name:
        raise HTTPException(status_code=400, detail="phone and name required")
    if db.query(Customer).filter(Customer.phone == phone).first():
        raise HTTPException(status_code=400, detail="Phone already exists")
    c = Customer(
        phone=phone,
        name=name,
        agent_code=body.get("agent_code") or None,
        notes=body.get("notes") or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "phone": c.phone, "name": c.name, "agent_code": c.agent_code}


@router.patch("/customers/{phone}")
def update_customer(
    phone: str,
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    c = db.query(Customer).filter(Customer.phone == phone).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    for field in ["name", "agent_code", "notes"]:
        if field in body:
            setattr(c, field, body[field] or None)
    db.commit()
    return {"phone": c.phone, "name": c.name, "agent_code": c.agent_code}


@router.delete("/customers/{phone}")
def delete_customer(
    phone: str,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    c = db.query(Customer).filter(Customer.phone == phone).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ── Gift Requests ─────────────────────────────────────────────

@router.get("/gift-requests")
def list_gift_requests(
    month: Optional[str] = None,
    agent_code: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    query = db.query(GiftRequest)
    if month:
        year, mon = map(int, month.split("-"))
        query = query.filter(
            extract("year", GiftRequest.created_at) == year,
            extract("month", GiftRequest.created_at) == mon,
        )
    if agent_code:
        query = query.filter(GiftRequest.agent_code == agent_code)
    if status:
        query = query.filter(GiftRequest.status == status)
    requests = query.order_by(GiftRequest.created_at.desc()).all()

    active = [r for r in requests if r.status != "已取消"]
    return {
        "gift_total_sum": sum(r.gift_total for r in active),
        "request_count": len(active),
        "items": [_gift_request_dict(r) for r in requests],
    }


@router.patch("/gift-requests/{request_id}")
def update_gift_request(
    request_id: int,
    body: dict,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    _auth(authorization)
    req = db.query(GiftRequest).filter(GiftRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Gift request not found")
    if "status" in body:
        req.status = body["status"]
    if "notes" in body:
        req.notes = body["notes"] or None
    db.commit()
    db.refresh(req)
    return _gift_request_dict(req)
