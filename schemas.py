from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class AgentCreate(BaseModel):
    name: str
    code: str
    discount_rate: float
    phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    discount_rate: Optional[float] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class AgentOut(BaseModel):
    id: int
    name: str
    code: str
    discount_rate: float
    phone: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class OrderItemCreate(BaseModel):
    product_code: Optional[str] = None
    product_name: str
    product_series: Optional[str] = None
    variant_label: Optional[str] = None
    unit_price: float
    quantity: int


class OrderItemOut(BaseModel):
    id: int
    product_code: Optional[str]
    product_name: str
    product_series: Optional[str]
    variant_label: Optional[str]
    unit_price: float
    quantity: int
    item_subtotal: float

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    agent_code: Optional[str] = None
    customer_name: str
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    payment_method: str = "匯款"
    shipping_fee: float = 0
    notes: Optional[str] = None
    items: List[OrderItemCreate]


class OrderUpdate(BaseModel):
    status: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    shipping_fee: Optional[float] = None
    customer_address: Optional[str] = None
    notes: Optional[str] = None


class OrderOut(BaseModel):
    id: int
    order_number: str
    agent_id: Optional[int]
    agent: Optional[AgentOut]
    customer_name: str
    customer_phone: Optional[str]
    customer_address: Optional[str]
    payment_method: str
    payment_status: str
    shipping_fee: float
    subtotal: float
    discount_amount: float
    final_amount: float
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemOut]

    class Config:
        from_attributes = True
