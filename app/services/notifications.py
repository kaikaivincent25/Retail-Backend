from sqlalchemy.orm import Session

from app.models.customer_order import CustomerOrder
from app.models.notification import NotificationChannel, NotificationEvent


def queue_order_notification(
    db: Session,
    order: CustomerOrder,
    event_type: str,
    message: str,
    *,
    include_shop: bool = False,
) -> None:
    """Queue provider-neutral notifications; a worker sends them when credentials exist."""
    recipients = [(NotificationChannel.SMS, order.customer_phone)]
    if include_shop:
        # Shop WhatsApp/SMS destination is intentionally a future shop setting.
        return
    for channel, recipient in recipients:
        db.add(NotificationEvent(
            shop_id=order.shop_id,
            order_id=order.id,
            channel=channel,
            event_type=event_type,
            recipient=recipient,
            message=message,
            payload={"order_number": order.order_number, "status": order.status.value},
        ))
