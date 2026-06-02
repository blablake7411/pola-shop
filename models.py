from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base
import json

TIERS = [
    {"tier": 1, "min_retail": 0,      "max_retail": 70000,  "discount": 0.80},
    {"tier": 2, "min_retail": 70000,  "max_retail": 140000, "discount": 0.75},
    {"tier": 3, "min_retail": 140000, "max_retail": None,   "discount": 0.70},
]
STORE_TIERS = [
    {"tier": 1, "min_retail": 0,      "max_retail": 300000, "discount": 0.80},
    {"tier": 2, "min_retail": 300000, "max_retail": None,   "discount": 0.70},
]
YOUR_COST_RATE = 0.60
DIRECT_DISCOUNT = 0.90  # 沒有業務代碼的直客


def get_discount(tier: int) -> float:
    for t in TIERS:
        if t["tier"] == tier:
            return t["discount"]
    return 0.80


def get_store_discount(tier: int) -> float:
    for t in STORE_TIERS:
        if t["tier"] == tier:
            return t["discount"]
    return 0.80


def get_agent_discount(agent) -> float:
    agent_type = getattr(agent, "agent_type", "personal")
    if agent_type == "owner":
        return 0.60
    if agent_type == "store":
        return get_store_discount(agent.current_tier)
    return get_discount(agent.current_tier)


def calc_tier_by_retail(retail: int) -> int:
    for t in reversed(TIERS):
        if retail >= t["min_retail"]:
            return t["tier"]
    return 1


def calc_store_tier_by_retail(retail: int) -> int:
    for t in reversed(STORE_TIERS):
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
    phone = Column(String, index=True)
    agent_type = Column(String, default="personal", nullable=False)  # personal / store
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
    payment_method = Column(String, nullable=True)
    notes = Column(Text)
    status = Column(String, default="待確認")
    agent_tier = Column(Integer)
    agent_discount = Column(Float)
    retail_total = Column(Integer, default=0)
    agent_cost_total = Column(Integer, default=0)
    discount_amount = Column(Integer, default=0, nullable=True)
    shipping_fee = Column(Integer, default=0, nullable=True)
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


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


class GiftRequest(Base):
    __tablename__ = "gift_requests"

    id = Column(Integer, primary_key=True)
    agent_code = Column(String, ForeignKey("agents.code"), nullable=False, index=True)
    customer_name = Column(String, nullable=False)
    customer_address = Column(Text, nullable=False)
    eligible_amount = Column(Integer, nullable=False)  # 客人消費原價
    gift_items = Column(Text, nullable=False)           # JSON list
    gift_total = Column(Integer, nullable=False, default=0)
    status = Column(String, default="待處理")           # 待處理 / 已完成 / 已取消
    notes = Column(Text)
    created_at = Column(DateTime, default=now_utc)

    agent = relationship("Agent")

    def items_list(self):
        try:
            return json.loads(self.gift_items)
        except Exception:
            return []
