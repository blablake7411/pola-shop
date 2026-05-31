from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

TIERS = [
    {"tier": 1, "min_retail": 0, "max_retail": 70000, "discount": 0.80},
    {"tier": 2, "min_retail": 70000, "max_retail": 140000, "discount": 0.75},
    {"tier": 3, "min_retail": 140000, "max_retail": None, "discount": 0.70},
]
YOUR_COST_RATE = 0.60


def get_discount(tier: int) -> float:
    for t in TIERS:
        if t["tier"] == tier:
            return t["discount"]
    return 0.80


def calc_tier_by_retail(retail: int) -> int:
    for t in reversed(TIERS):
        if retail >= t["min_retail"]:
            return t["tier"]
    return 1


def now_utc():
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    current_tier = Column(Integer, nullable=False, default=1)
    manual_override = Column(Boolean, default=False)
    joined_at = Column(String, nullable=False)
    created_at = Column(DateTime, default=now_utc)

    orders = relationship("Order", back_populates="agent", foreign_keys="Order.agent_code")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_number = Column(String, unique=True, nullable=False, index=True)
    agent_code = Column(String, ForeignKey("agents.code"), nullable=True)
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String)
    customer_address = Column(Text)
    payment_method = Column(String, nullable=False)
    notes = Column(Text)
    status = Column(String, default="待確認")
    agent_tier = Column(Integer)
    agent_discount = Column(Float)
    retail_total = Column(Integer, default=0)
    agent_cost_total = Column(Integer, default=0)
    created_at = Column(DateTime, default=now_utc)
    confirmed_at = Column(DateTime)
    shipped_at = Column(DateTime)

    agent = relationship("Agent", back_populates="orders", foreign_keys=[agent_code])
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_code = Column(String)
    product_name = Column(String, nullable=False)
    product_series = Column(String)
    variant_label = Column(String)
    unit_price = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)

    order = relationship("Order", back_populates="items")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    agent_code = Column(String, ForeignKey("agents.code"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_utc)

    agent = relationship("Agent")
