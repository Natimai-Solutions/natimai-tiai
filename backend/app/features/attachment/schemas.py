"""What the API says of an attachment: shared by its routes and by the
journal's lines (``routes/interventions.py:InterventionOut``)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: uuid.UUID
    intervention_id: uuid.UUID
    filename: str
    content_type: str
    size: int
    uploaded_by: str
    created_at: datetime

    model_config = {"from_attributes": True}
